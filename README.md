Environment Note

bot_framework intentionally has no virtual environment of its own.
It is installed editable into d4_bot's virtual environment at:
C:\Users\brian\source\repos\d4_bot\.venv

`framework.*` resolves from that shared environment, and framework tests must be run from bot_framework using:

```
C:\Users\brian\source\repos\d4_bot\.venv\Scripts\python -m pytest -q
```

Do not create a virtual environment inside bot_framework. A local bot_framework `.venv` starts empty, misses required dependencies, and framework tests will not run there.
