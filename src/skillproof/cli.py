"""Command line entry point."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local SkillProof review workspace")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (keep loopback for local-only use)")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    uvicorn.run("skillproof.main:app", host=args.host, port=args.port, reload=False)
