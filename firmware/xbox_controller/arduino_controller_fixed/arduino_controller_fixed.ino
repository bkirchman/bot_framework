#include <WiFi.h>
#include <WiFiUdp.h>
#include <Joystick_ESP32S2.h>
#include "DFRobot_DF2301Q.h"

/*
 * CHANGELOG - v2.1 Duration Extensions
 * ===================================================
 * v2.1 Changes:
 * 1. Added button_N_duration commands for timed self-release of button_N
 * 2. Added hat_duration command for timed self-release of hat_x/hat_y to neutral
 * 3. Added ack/complete responses for the new duration commands
 *
 * v2.0 Changes:
 * 1. Dynamic response IP - responds to sender's IP (no hardcoded IP needed)
 * 2. Command sequence numbers (seq) for request/response correlation
 * 3. Unified JSON response format with msg_type field
 * 4. Added 'ping' command for connection testing
 * 5. Clear ack (immediate) vs complete (after duration) responses
 * 6. Response modes: 0=none, 1=ack only, 2=ack+complete
 * 7. Flexible response fields per command type:
 *    - ping:    {msg_type:"pong", seq:N}
 *    - aim:     {msg_type, seq, cmd:"aim", x, y, dur, [actual_us, err_us]}
 *    - move:    {msg_type, seq, cmd:"move", x, y, dur, [actual_us, err_us]}
 *    - trigger: {msg_type, seq, cmd:"trigger", val, dur, [actual_us, err_us]}
 *    - button:  {msg_type:"ack", seq, cmd:"button", btn, pressed}
 *    - reload:  {msg_type:"ack", seq, cmd:"reload"} (fixed 50ms press of button_0)
 *
 * Previous updates:
 * - Timing instrumentation with microsecond precision
 * - State-based control for aim and movement sticks
 * - Non-blocking duration control handled by Arduino
 * - Proper reset values for all axes
 */

// DEBUG flag - set to true to enable serial output
const bool DEBUG = false;

// Wi-Fi credentials
const char *ssid = "BK-Net";
const char *password = "6480335A";

// UDP for receiving commands
WiFiUDP udp;
const unsigned int udpPort = 5005;
char packetBuffer[512];

// UDP for sending responses back to Python
WiFiUDP udp_response;
const unsigned int response_port = 5006;

// Dynamic response target (captured from incoming packet sender)
IPAddress response_ip;
bool response_ip_valid = false;

// Current command sequence number (received from Python)
uint32_t current_seq = 0;

// Response mode: 0=none, 1=ack only, 2=ack+complete
uint8_t response_mode = 0;

const int LED_BUILTIN = 13;
int messageCounter = 0;

// Initialize the joystick
Joystick_ joystick(JOYSTICK_DEFAULT_REPORT_ID, JOYSTICK_TYPE_GAMEPAD,
                   15, 1, true, true, true,
                   true, true, true, false, false,
                   false, false, false);

// State-based command structure
struct AxisCommand
{
    int8_t x_value;
    int8_t y_value;
    uint32_t duration_ms;
    uint32_t start_time;
    bool active;
    int8_t reset_x;                    // Value to reset to when inactive
    int8_t reset_y;                    // Value to reset to when inactive
    unsigned long timing_start_micros; // Microsecond precision timing
    uint32_t seq;                      // Sequence number for correlation
    uint8_t resp_mode;                 // Response mode for this command
};

// Initialize with proper reset values (added seq=0, resp_mode=0)
AxisCommand right_stick = {0, 0, 0, 0, false, 0, 0, 0, 0, 0};   // Rx, Ry (aim) reset to 0
AxisCommand left_stick = {0, 0, 0, 0, false, 0, 0, 0, 0, 0};    // X, Y (move) reset to 0
AxisCommand trigger = {0, 0, 0, 0, false, -100, 0, 0, 0, 0};    // axis_5 (right trigger) resets to -100 (released)
AxisCommand trigger_lt = {0, 0, 0, 0, false, -100, 0, 0, 0, 0}; // axis_4 (left trigger) resets to -100 (released)

// Reload state (button_0 press, fixed 50ms duration)
struct ReloadCommand
{
    bool active;
    uint32_t start_time;
    uint32_t seq;
    uint8_t resp_mode;
};
ReloadCommand reload_cmd = {false, 0, 0, 0};
const uint32_t RELOAD_DURATION_MS = 50;

const uint8_t MAX_BUTTONS = 15;

struct ButtonDurationCommand
{
    bool active;
    bool pending_press;
    uint32_t start_time;
    uint32_t duration_ms;
    unsigned long timing_start_micros;
    uint32_t seq;
    uint8_t resp_mode;
};
ButtonDurationCommand button_duration_cmds[MAX_BUTTONS] = {};

struct HatDurationCommand
{
    bool active;
    bool pending_set;
    uint32_t start_time;
    uint32_t duration_ms;
    unsigned long timing_start_micros;
    uint32_t seq;
    uint8_t resp_mode;
    int8_t x_value;
    int8_t y_value;
};
HatDurationCommand hat_duration_cmd = {false, false, 0, 0, 0, 0, 0, 0, 0};

int hat_x_state = 0;
int hat_y_state = 0;

void setup()
{
    Serial.begin(115200);
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
    joystick.begin();

    // Configure axis ranges to -100 to 100
    joystick.setXAxisRange(-100, 100);
    joystick.setYAxisRange(-100, 100);
    joystick.setZAxisRange(-100, 100);
    joystick.setRxAxisRange(-100, 100);
    joystick.setRyAxisRange(-100, 100);
    joystick.setRzAxisRange(-100, 100);

    // Set initial positions
    joystick.setRxAxis(0); // Right stick X (not used for aim in current setup)
    joystick.setRyAxis(-100); // Right trigger (axis_5) - released
    joystick.setRzAxis(0);    // Right stick Y (aim vertical)
    joystick.setXAxis(0);     // Left stick X
    joystick.setYAxis(0);     // Left stick Y
    joystick.setZAxis(0);     // Right stick X (aim horizontal) - note: Z maps to right stick X for aim

    joystick.setHatSwitch(0, 0); // Initialize to neutral position

    WiFi.begin(ssid, password);
    Serial.print("Connecting to Wi-Fi...");
    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println("\nConnected to Wi-Fi.");
    Serial.println(WiFi.localIP());

    udp.begin(udpPort);

    // Note: We don't need to begin() the response UDP socket
    // We'll use beginPacket() which handles it

    Serial.println("UDP server started.");
    Serial.println("Begin ok!");

     // Set initial positions
    joystick.setRxAxis(-100); // Right stick X (not used for aim in current setup)
    joystick.setRyAxis(-100); // Right trigger (axis_5) - released
    joystick.setRzAxis(0);    // Right stick Y (aim vertical)
    joystick.setXAxis(0);     // Left stick X
    joystick.setYAxis(0);     // Left stick Y
    joystick.setZAxis(0);     // Right stick X (aim horizontal) - note: Z maps to right stick X for aim

    joystick.setHatSwitch(0, -1); // Initialize to neutral position

}

void loop()
{
    // Check for new UDP commands (non-blocking)
    int packetSize = udp.parsePacket();
    if (packetSize > 0)
    {
        // Capture sender's IP for responses (dynamic, no hardcoded IP needed)
        response_ip = udp.remoteIP();
        response_ip_valid = true;

        int len = udp.read(packetBuffer, sizeof(packetBuffer));
        if (len > 0)
        {
            packetBuffer[len] = '\0';

            // Toggle LED to show packet received
            messageCounter++;
            digitalWrite(LED_BUILTIN, messageCounter % 2);

            // Remove JSON characters in-place (avoid String operations)
            int writePos = 0;
            for (int readPos = 0; readPos < len; readPos++)
            {
                char c = packetBuffer[readPos];
                if (c != '{' && c != '}' && c != '"' && c != ' ' && c != '\n' && c != '\r')
                {
                    packetBuffer[writePos++] = c;
                }
            }
            packetBuffer[writePos] = '\0';

            processCommands(String(packetBuffer));
        }
    }

    // Update stick states based on timing
    updateStickStates();
}

// Send response only if we have a valid IP and response_mode allows it
void sendResponse(const char *response)
{
    if (!response_ip_valid)
        return;

    udp_response.beginPacket(response_ip, response_port);
    udp_response.write((uint8_t *)response, strlen(response));
    udp_response.endPacket();

    if (DEBUG)
    {
        Serial.print("Sent response to ");
        Serial.print(response_ip);
        Serial.print(": ");
        Serial.print(response);
    }
}

// Send pong response for ping command
void sendPong(uint32_t seq)
{
    char response[64];
    snprintf(response, sizeof(response), "{\"msg_type\":\"pong\",\"seq\":%u}\n", seq);
    sendResponse(response);
}

// Send ack for aim command
void sendAimAck(uint32_t seq, int8_t x, int8_t y, uint32_t dur)
{
    char response[128];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"aim\",\"x\":%d,\"y\":%d,\"dur\":%u}\n",
             seq, x, y, dur);
    sendResponse(response);
}

// Send complete for aim command (with timing data)
void sendAimComplete(uint32_t seq, int8_t x, int8_t y, uint32_t dur, unsigned long actual_us)
{
    char response[160];
    int32_t err_us = (int32_t)actual_us - ((int32_t)dur * 1000);
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"complete\",\"seq\":%u,\"cmd\":\"aim\",\"x\":%d,\"y\":%d,\"dur\":%u,\"actual_us\":%lu,\"err_us\":%d}\n",
             seq, x, y, dur, actual_us, err_us);
    sendResponse(response);
}

// Send ack for move command
void sendMoveAck(uint32_t seq, int8_t x, int8_t y, uint32_t dur)
{
    char response[128];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"move\",\"x\":%d,\"y\":%d,\"dur\":%u}\n",
             seq, x, y, dur);
    sendResponse(response);
}

// Send complete for move command (with timing data)
void sendMoveComplete(uint32_t seq, int8_t x, int8_t y, uint32_t dur, unsigned long actual_us)
{
    char response[160];
    int32_t err_us = (int32_t)actual_us - ((int32_t)dur * 1000);
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"complete\",\"seq\":%u,\"cmd\":\"move\",\"x\":%d,\"y\":%d,\"dur\":%u,\"actual_us\":%lu,\"err_us\":%d}\n",
             seq, x, y, dur, actual_us, err_us);
    sendResponse(response);
}

// Send ack for trigger_lt command
void sendTriggerLtAck(uint32_t seq, int8_t val, uint32_t dur)
{
    char response[128];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"trigger_lt\",\"val\":%d,\"dur\":%u}\n",
             seq, val, dur);
    sendResponse(response);
}

// Send complete for trigger_lt command (with timing data)
void sendTriggerLtComplete(uint32_t seq, int8_t val, uint32_t dur, unsigned long actual_us)
{
    char response[160];
    int32_t err_us = (int32_t)actual_us - ((int32_t)dur * 1000);
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"complete\",\"seq\":%u,\"cmd\":\"trigger_lt\",\"val\":%d,\"dur\":%u,\"actual_us\":%lu,\"err_us\":%d}\n",
             seq, val, dur, actual_us, err_us);
    sendResponse(response);
}

// Send ack for trigger command
void sendTriggerAck(uint32_t seq, int8_t val, uint32_t dur)
{
    char response[128];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"trigger\",\"val\":%d,\"dur\":%u}\n",
             seq, val, dur);
    sendResponse(response);
}

// Send complete for trigger command (with timing data)
void sendTriggerComplete(uint32_t seq, int8_t val, uint32_t dur, unsigned long actual_us)
{
    char response[160];
    int32_t err_us = (int32_t)actual_us - ((int32_t)dur * 1000);
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"complete\",\"seq\":%u,\"cmd\":\"trigger\",\"val\":%d,\"dur\":%u,\"actual_us\":%lu,\"err_us\":%d}\n",
             seq, val, dur, actual_us, err_us);
    sendResponse(response);
}

// Send ack for button command
void sendButtonAck(uint32_t seq, int btn, int pressed)
{
    char response[96];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"button\",\"btn\":%d,\"pressed\":%d}\n",
             seq, btn, pressed);
    sendResponse(response);
}

// Send ack for button duration command
void sendButtonDurationAck(uint32_t seq, int btn, uint32_t dur)
{
    char response[112];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"button_duration\",\"btn\":%d,\"dur\":%u}\n",
             seq, btn, dur);
    sendResponse(response);
}

// Send complete for button duration command (with timing data)
void sendButtonDurationComplete(uint32_t seq, int btn, uint32_t dur, unsigned long actual_us)
{
    char response[160];
    int32_t err_us = (int32_t)actual_us - ((int32_t)dur * 1000);
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"complete\",\"seq\":%u,\"cmd\":\"button_duration\",\"btn\":%d,\"dur\":%u,\"actual_us\":%lu,\"err_us\":%d}\n",
             seq, btn, dur, actual_us, err_us);
    sendResponse(response);
}

// Send ack for hat duration command
void sendHatDurationAck(uint32_t seq, int8_t x, int8_t y, uint32_t dur)
{
    char response[128];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"hat_duration\",\"x\":%d,\"y\":%d,\"dur\":%u}\n",
             seq, x, y, dur);
    sendResponse(response);
}

// Send complete for hat duration command (with timing data)
void sendHatDurationComplete(uint32_t seq, int8_t x, int8_t y, uint32_t dur, unsigned long actual_us)
{
    char response[176];
    int32_t err_us = (int32_t)actual_us - ((int32_t)dur * 1000);
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"complete\",\"seq\":%u,\"cmd\":\"hat_duration\",\"x\":%d,\"y\":%d,\"dur\":%u,\"actual_us\":%lu,\"err_us\":%d}\n",
             seq, x, y, dur, actual_us, err_us);
    sendResponse(response);
}

// Send ack for reload command
void sendReloadAck(uint32_t seq)
{
    char response[64];
    snprintf(response, sizeof(response),
             "{\"msg_type\":\"ack\",\"seq\":%u,\"cmd\":\"reload\"}\n", seq);
    sendResponse(response);
}

void updateStickStates()
{
    uint32_t current_time = millis();

    // Check right stick (aiming) timer
    if (right_stick.active)
    {
        if (current_time - right_stick.start_time >= right_stick.duration_ms)
        {
            // Calculate actual duration in microseconds
            unsigned long actual_us = micros() - right_stick.timing_start_micros;

            // Send complete response if response_mode == 2
            if (right_stick.resp_mode == 2)
            {
                sendAimComplete(right_stick.seq, right_stick.x_value, right_stick.y_value,
                                right_stick.duration_ms, actual_us);
            }

            // Duration expired - reset to initial values
            right_stick.x_value = right_stick.reset_x;
            right_stick.y_value = right_stick.reset_y;
            right_stick.active = false;
            joystick.setZAxis(right_stick.reset_x);  // Match axis_2 (aim horizontal)
            joystick.setRzAxis(right_stick.reset_y); // Match axis_3 (aim vertical)

            if (DEBUG)
                Serial.println("Right stick reset to initial position");
        }
        else
        {
            // Still active - maintain position
            joystick.setZAxis(right_stick.x_value);  // Match axis_2
            joystick.setRzAxis(right_stick.y_value); // Match axis_3
        }
    }

    // Check left stick (movement) timer
    if (left_stick.active)
    {
        if (current_time - left_stick.start_time >= left_stick.duration_ms)
        {
            // Calculate actual duration in microseconds
            unsigned long actual_us = micros() - left_stick.timing_start_micros;

            // Send complete response if response_mode == 2
            if (left_stick.resp_mode == 2)
            {
                sendMoveComplete(left_stick.seq, left_stick.x_value, left_stick.y_value,
                                 left_stick.duration_ms, actual_us);
            }

            // Duration expired - reset to initial values
            left_stick.x_value = left_stick.reset_x;
            left_stick.y_value = left_stick.reset_y;
            left_stick.active = false;
            joystick.setXAxis(left_stick.reset_x);
            joystick.setYAxis(left_stick.reset_y);

            if (DEBUG)
                Serial.println("Left stick reset to initial position");
        }
        else
        {
            // Still active - maintain position
            joystick.setXAxis(left_stick.x_value);
            joystick.setYAxis(left_stick.y_value);
        }
    }

    // Check trigger timer
    if (trigger.active)
    {
        if (current_time - trigger.start_time >= trigger.duration_ms)
        {
            // Calculate actual duration in microseconds
            unsigned long actual_us = micros() - trigger.timing_start_micros;

            // Send complete response if response_mode == 2
            if (trigger.resp_mode == 2)
            {
                sendTriggerComplete(trigger.seq, trigger.x_value, trigger.duration_ms, actual_us);
            }

            // Duration expired - reset to released
            trigger.x_value = trigger.reset_x; // -100 (released)
            trigger.active = false;
            joystick.setRyAxis(trigger.reset_x); // axis_5 (right trigger)

            if (DEBUG)
                Serial.println("Trigger reset to released position");
        }
        else
        {
            // Still active - maintain pressed
            joystick.setRyAxis(trigger.x_value); // axis_5
        }
    }

    // Check trigger_lt timer
    if (trigger_lt.active)
    {
        if (current_time - trigger_lt.start_time >= trigger_lt.duration_ms)
        {
            unsigned long actual_us = micros() - trigger_lt.timing_start_micros;
            if (trigger_lt.resp_mode == 2)
            {
                sendTriggerLtComplete(trigger_lt.seq, trigger_lt.x_value, trigger_lt.duration_ms, actual_us);
            }
            trigger_lt.x_value = trigger_lt.reset_x;
            trigger_lt.active = false;
            joystick.setRxAxis(trigger_lt.reset_x); // axis_4 (left trigger)
            if (DEBUG)
                Serial.println("Trigger LT reset to released position");
        }
        else
        {
            joystick.setRxAxis(trigger_lt.x_value); // axis_4
        }
    }

    // Check reload timer (fixed 50ms press of button_0)
    if (reload_cmd.active)
    {
        if (current_time - reload_cmd.start_time >= RELOAD_DURATION_MS)
        {
            reload_cmd.active = false;
            joystick.setButton(0, 0);
            if (DEBUG)
                Serial.println("Reload complete, button_0 released");
        }
    }

    // Check button duration timers (button_N_duration)
    for (uint8_t button_idx = 0; button_idx < MAX_BUTTONS; button_idx++)
    {
        if (button_duration_cmds[button_idx].active)
        {
            if (current_time - button_duration_cmds[button_idx].start_time >= button_duration_cmds[button_idx].duration_ms)
            {
                unsigned long actual_us = micros() - button_duration_cmds[button_idx].timing_start_micros;
                if (button_duration_cmds[button_idx].resp_mode == 2)
                {
                    sendButtonDurationComplete(button_duration_cmds[button_idx].seq,
                                               button_idx,
                                               button_duration_cmds[button_idx].duration_ms,
                                               actual_us);
                }

                joystick.setButton(button_idx, 0);
                button_duration_cmds[button_idx].active = false;
                button_duration_cmds[button_idx].pending_press = false;

                if (DEBUG)
                {
                    Serial.print("Button ");
                    Serial.print(button_idx);
                    Serial.println(" duration complete, released");
                }
            }
        }
    }

    // Check hat duration timer (hat_duration)
    if (hat_duration_cmd.active)
    {
        if (current_time - hat_duration_cmd.start_time >= hat_duration_cmd.duration_ms)
        {
            unsigned long actual_us = micros() - hat_duration_cmd.timing_start_micros;
            if (hat_duration_cmd.resp_mode == 2)
            {
                sendHatDurationComplete(hat_duration_cmd.seq,
                                        hat_duration_cmd.x_value,
                                        hat_duration_cmd.y_value,
                                        hat_duration_cmd.duration_ms,
                                        actual_us);
            }

            hat_x_state = 0;
            hat_y_state = 0;
            joystick.setHatSwitch(0, mapHatDirection(0, 0));
            hat_duration_cmd.active = false;
            hat_duration_cmd.pending_set = false;

            if (DEBUG)
                Serial.println("Hat duration complete, reset to neutral");
        }
    }
}

void processCommands(String packet)
{
    // Parse seq and resp at packet level FIRST (before splitting into commands)
    int seq_idx = packet.indexOf("seq:");
    if (seq_idx != -1)
    {
        // Find end of seq value (next comma or end of string)
        int seq_end = packet.indexOf(',', seq_idx);
        if (seq_end == -1)
            seq_end = packet.length();
        current_seq = packet.substring(seq_idx + 4, seq_end).toInt();
    }

    int resp_idx = packet.indexOf("resp:");
    if (resp_idx != -1)
    {
        int resp_end = packet.indexOf(',', resp_idx);
        if (resp_end == -1)
            resp_end = packet.length();
        response_mode = packet.substring(resp_idx + 5, resp_end).toInt();
    }
    else
    {
        response_mode = 0;
    }

    if (DEBUG)
    {
        Serial.print("Packet seq=");
        Serial.print(current_seq);
        Serial.print(" resp=");
        Serial.println(response_mode);
    }

    // Now process individual commands
    int start = 0;
    int end = packet.indexOf(',');

    while (end != -1)
    {
        String command = packet.substring(start, end);
        handleCommand(command);
        start = end + 1;
        end = packet.indexOf(',', start);
    }

    handleCommand(packet.substring(start));
}

void handleCommand(String command)
{
    // Skip seq: and resp: commands (already parsed at packet level)
    if (command.startsWith("seq:") || command.startsWith("resp:"))
    {
        return;
    }

    // Handle ping command (connection test)
    if (command.startsWith("ping:"))
    {
        sendPong(current_seq);
        if (DEBUG)
            Serial.println("Ping received, pong sent");
        return;
    }

    // State-based right stick command (for aiming)
    if (command.startsWith("aim_x:"))
    {
        right_stick.x_value = command.substring(6).toInt();
        right_stick.start_time = millis();
        right_stick.active = true;
        right_stick.seq = current_seq;
        right_stick.resp_mode = response_mode;
        if (DEBUG)
        {
            Serial.print("Aim X: ");
            Serial.println(right_stick.x_value);
        }
    }
    else if (command.startsWith("aim_y:"))
    {
        right_stick.y_value = command.substring(6).toInt();
        right_stick.start_time = millis();
        right_stick.active = true;
        right_stick.seq = current_seq;
        right_stick.resp_mode = response_mode;
        if (DEBUG)
        {
            Serial.print("Aim Y: ");
            Serial.println(right_stick.y_value);
        }
    }
    else if (command.startsWith("aim_duration:"))
    {
        right_stick.duration_ms = command.substring(13).toInt();
        right_stick.timing_start_micros = micros(); // Start precision timing
        right_stick.seq = current_seq;
        right_stick.resp_mode = response_mode;
        // Send ack after duration is set (command is complete)
        if (response_mode >= 1)
        {
            sendAimAck(current_seq, right_stick.x_value, right_stick.y_value, right_stick.duration_ms);
        }
        if (DEBUG)
        {
            Serial.print("Aim Duration: ");
            Serial.println(right_stick.duration_ms);
        }
    }
    // State-based left stick command (for movement)
    else if (command.startsWith("move_x:"))
    {
        left_stick.x_value = command.substring(7).toInt();
        left_stick.start_time = millis();
        left_stick.active = true;
        left_stick.seq = current_seq;
        left_stick.resp_mode = response_mode;
        if (DEBUG)
        {
            Serial.print("Move X: ");
            Serial.println(left_stick.x_value);
        }
    }
    else if (command.startsWith("move_y:"))
    {
        left_stick.y_value = command.substring(7).toInt();
        left_stick.start_time = millis();
        left_stick.active = true;
        left_stick.seq = current_seq;
        left_stick.resp_mode = response_mode;
        if (DEBUG)
        {
            Serial.print("Move Y: ");
            Serial.println(left_stick.y_value);
        }
    }
    else if (command.startsWith("move_duration:"))
    {
        left_stick.duration_ms = command.substring(14).toInt();
        left_stick.timing_start_micros = micros(); // Start precision timing
        left_stick.seq = current_seq;
        left_stick.resp_mode = response_mode;
        // Send ack after duration is set (command is complete)
        if (response_mode >= 1)
        {
            sendMoveAck(current_seq, left_stick.x_value, left_stick.y_value, left_stick.duration_ms);
        }
        if (DEBUG)
        {
            Serial.print("Move Duration: ");
            Serial.println(left_stick.duration_ms);
        }
    }
    // State-based trigger command (for shooting)
    else if (command.startsWith("trigger:"))
    {
        trigger.x_value = command.substring(8).toInt();
        trigger.start_time = millis();
        trigger.active = true;
        trigger.seq = current_seq;
        trigger.resp_mode = response_mode;
        if (DEBUG)
        {
            Serial.print("Trigger: ");
            Serial.println(trigger.x_value);
        }
    }
    else if (command.startsWith("trigger_duration:"))
    {
        trigger.duration_ms = command.substring(17).toInt();
        trigger.timing_start_micros = micros(); // Start precision timing
        trigger.seq = current_seq;
        trigger.resp_mode = response_mode;
        // Send ack after duration is set (command is complete)
        if (response_mode >= 1)
        {
            sendTriggerAck(current_seq, trigger.x_value, trigger.duration_ms);
        }
        if (DEBUG)
        {
            Serial.print("Trigger Duration: ");
            Serial.println(trigger.duration_ms);
        }
    }
    // State-based trigger_lt command (for left trigger)
    else if (command.startsWith("trigger_lt:"))
    {
        trigger_lt.x_value = command.substring(11).toInt();
        trigger_lt.start_time = millis();
        trigger_lt.active = true;
        trigger_lt.seq = current_seq;
        trigger_lt.resp_mode = response_mode;
        if (DEBUG)
        {
            Serial.print("Trigger LT: ");
            Serial.println(trigger_lt.x_value);
        }
    }
    else if (command.startsWith("trigger_lt_duration:"))
    {
        trigger_lt.duration_ms = command.substring(20).toInt();
        trigger_lt.timing_start_micros = micros();
        trigger_lt.seq = current_seq;
        trigger_lt.resp_mode = response_mode;
        if (response_mode >= 1)
        {
            sendTriggerLtAck(current_seq, trigger_lt.x_value, trigger_lt.duration_ms);
        }
        if (DEBUG)
        {
            Serial.print("Trigger LT Duration: ");
            Serial.println(trigger_lt.duration_ms);
        }
    }
    // LEGACY: Backward compatible with old axis commands
    else if (command.startsWith("axis_"))
    {
        int axisIndex = command.charAt(5) - '0';
        int value = command.substring(7).toInt();
        switch (axisIndex)
        {
        case 0:
            joystick.setXAxis(value);
            break;
        case 1:
            joystick.setYAxis(value);
            break;
        case 2:
            joystick.setZAxis(value);
            break;
        case 3:
            joystick.setRzAxis(value);
            break;
        case 4:
            joystick.setRxAxis(value);
            break;
        case 5:
            joystick.setRyAxis(value);
            break;
        }
        if (DEBUG)
        {
            Serial.print("Axis ");
            Serial.print(axisIndex);
            Serial.print(": ");
            Serial.println(value);
        }
    }
    else if (command.startsWith("hat_x:"))
    {
        hat_x_state = command.substring(6).toInt();
        joystick.setHatSwitch(0, mapHatDirection(hat_x_state, hat_y_state));
        hat_duration_cmd.pending_set = true;
        if (hat_duration_cmd.active)
        {
            hat_duration_cmd.active = false;
        }
        if (DEBUG)
        {
            Serial.print("Hat X: ");
            Serial.println(hat_x_state);
        }
    }
    else if (command.startsWith("hat_y:"))
    {
        hat_y_state = command.substring(6).toInt();
        joystick.setHatSwitch(0, mapHatDirection(hat_x_state, hat_y_state));
        hat_duration_cmd.pending_set = true;
        if (hat_duration_cmd.active)
        {
            hat_duration_cmd.active = false;
        }
        if (DEBUG)
        {
            Serial.print("Hat Y: ");
            Serial.println(hat_y_state);
        }
    }
    else if (command.startsWith("hat_duration:"))
    {
        uint32_t duration_ms = command.substring(13).toInt();
        if (hat_duration_cmd.pending_set)
        {
            hat_duration_cmd.duration_ms = duration_ms;
            hat_duration_cmd.start_time = millis();
            hat_duration_cmd.timing_start_micros = micros();
            hat_duration_cmd.seq = current_seq;
            hat_duration_cmd.resp_mode = response_mode;
            hat_duration_cmd.x_value = (int8_t)hat_x_state;
            hat_duration_cmd.y_value = (int8_t)hat_y_state;
            hat_duration_cmd.active = true;

            if (response_mode >= 1)
            {
                sendHatDurationAck(current_seq, hat_duration_cmd.x_value, hat_duration_cmd.y_value, duration_ms);
            }
        }
        if (DEBUG)
        {
            Serial.print("Hat Duration: ");
            Serial.println(duration_ms);
        }
    }
    else if (command.startsWith("button_") && command.indexOf("_duration:") != -1)
    {
        int duration_sep = command.indexOf("_duration:");
        int buttonIndex = command.substring(7, duration_sep).toInt();
        uint32_t duration_ms = command.substring(duration_sep + 10).toInt();

        if (buttonIndex >= 0 && buttonIndex < MAX_BUTTONS)
        {
            if (button_duration_cmds[buttonIndex].pending_press)
            {
                button_duration_cmds[buttonIndex].duration_ms = duration_ms;
                button_duration_cmds[buttonIndex].start_time = millis();
                button_duration_cmds[buttonIndex].timing_start_micros = micros();
                button_duration_cmds[buttonIndex].seq = current_seq;
                button_duration_cmds[buttonIndex].resp_mode = response_mode;
                button_duration_cmds[buttonIndex].active = true;

                if (response_mode >= 1)
                {
                    sendButtonDurationAck(current_seq, buttonIndex, duration_ms);
                }
            }
        }

        if (DEBUG)
        {
            Serial.print("Button Duration ");
            Serial.print(buttonIndex);
            Serial.print(": ");
            Serial.println(duration_ms);
        }
    }
    else if (command.startsWith("button_"))
    {
        int buttonIndex = command.substring(7, command.indexOf(':')).toInt();
        int value = command.substring(command.indexOf(':') + 1).toInt();
        joystick.setButton(buttonIndex, value);

        if (buttonIndex >= 0 && buttonIndex < MAX_BUTTONS)
        {
            if (value == 1)
            {
                button_duration_cmds[buttonIndex].pending_press = true;
                // A new press supersedes any currently running timer for this button.
                if (button_duration_cmds[buttonIndex].active)
                {
                    button_duration_cmds[buttonIndex].active = false;
                }
            }
            else if (value == 0)
            {
                button_duration_cmds[buttonIndex].pending_press = false;
                button_duration_cmds[buttonIndex].active = false;
            }
        }

        // Send ack for button if response_mode >= 1
        if (response_mode >= 1)
        {
            sendButtonAck(current_seq, buttonIndex, value);
        }
        if (DEBUG)
        {
            Serial.print("Button ");
            Serial.print(buttonIndex);
            Serial.print(": ");
            Serial.println(value);
        }
    }
    else if (command.startsWith("reload:"))
    {
        joystick.setButton(0, 1);
        reload_cmd.active = true;
        reload_cmd.start_time = millis();
        reload_cmd.seq = current_seq;
        reload_cmd.resp_mode = response_mode;
        if (response_mode >= 1)
        {
            sendReloadAck(current_seq);
        }
        if (DEBUG)
            Serial.println("Reload: button_0 pressed for 50ms");
    }
}

void reinforcements()
{
    if (DEBUG)
        Serial.println("Reinforcements Started");
    int in_between = 100;
    joystick.setButton(4, 1);
    delay(in_between);

    joystick.setHatSwitch(0, 0);
    delay(in_between);
    joystick.setHatSwitch(0, -1);
    delay(20);
    joystick.setHatSwitch(0, 180);
    delay(in_between);
    joystick.setHatSwitch(0, -1);
    delay(20);
    joystick.setHatSwitch(0, 90);
    delay(in_between);
    joystick.setHatSwitch(0, -1);
    delay(20);
    joystick.setHatSwitch(0, 270);
    delay(in_between);
    joystick.setHatSwitch(0, -1);
    delay(20);
    joystick.setHatSwitch(0, 0);
    delay(in_between);
    joystick.setHatSwitch(0, -1);
    delay(20);
    joystick.setButton(4, 0);
    delay(in_between);
    if (DEBUG)
        Serial.println("Reinforcements Completed");
}

int mapHatDirection(int xValue, int yValue)
{
    if (xValue == 0 && yValue == 1)
        return 0;
    if (xValue == 1 && yValue == 1)
        return 45;
    if (xValue == 1 && yValue == 0)
        return 90;
    if (xValue == 1 && yValue == -1)
        return 135;
    if (xValue == 0 && yValue == -1)
        return 180;
    if (xValue == -1 && yValue == -1)
        return 225;
    if (xValue == -1 && yValue == 0)
        return 270;
    if (xValue == -1 && yValue == 1)
        return 315;
    return -1;
}