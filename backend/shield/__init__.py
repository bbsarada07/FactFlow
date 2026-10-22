"""FactFlow Shield: deterministic scanning of emails and messages, and the action guard.

Core rule: untrusted content is data, never commands. Nothing in an email, page, image or
attachment can cause an action; only a human or a deterministic policy rule can authorise one.

The package is pure Python. It does not import FastAPI, the database or backend/config.py, so the
same detectors can run on an edge device. Persistence lives in services/shield_store.py.
"""
