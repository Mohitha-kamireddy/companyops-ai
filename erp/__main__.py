"""Start MiniERP:  python -m erp"""
import os

from erp.app import create_app

if __name__ == "__main__":
    # Debug/reloader stay off on purpose: the ERP should behave identically every run.
    create_app().run(host="127.0.0.1", port=int(os.environ.get("MINIERP_PORT", "8001")))
