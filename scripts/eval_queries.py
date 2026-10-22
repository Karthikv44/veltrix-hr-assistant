"""Interactive / automated query evaluation script for Veltrix PeopleOps Assistant.

Demonstrates queries across RAG, tools, hybrid, and permission refusals
against port 8000 (or in-process client if standalone).

Usage:
    uv run python scripts/eval_queries.py --base-url http://localhost:8000
"""

import argparse
import sys

import httpx

QUERIES = [
    {
        "name": "1. Policy RAG Query (India Medical Leave)",
        "employee_id": "EMP-001",
        "session_id": "eval-session-1",
        "message": "What is the policy for medical leave in India? Do I need a doctor certificate?",
        "expected_route": "rag",
    },
    {
        "name": "2. Balance Tool Query",
        "employee_id": "EMP-001",
        "session_id": "eval-session-2",
        "message": "What is my current annual leave balance?",
        "expected_route": "tool",
    },
    {
        "name": "3. Unauthorized Team Leave Query (Employee attempting to view team)",
        "employee_id": "EMP-001",
        "session_id": "eval-session-3",
        "message": "Show me the leave requests for all engineers in my department.",
        "expected_route": "tool",
    },
    {
        "name": "4. Precedence Query (Global vs Regional vs Remote memo)",
        "employee_id": "EMP-002",
        "session_id": "eval-session-4",
        "message": "How many days per week am I required to work from the office in Germany?",
        "expected_route": "rag",
    },
    {
        "name": "5. Out of Scope Query (Refusal)",
        "employee_id": "EMP-001",
        "session_id": "eval-session-5",
        "message": "Can you give me the Python code to sort an array?",
        "expected_route": "refuse",
    },
    {
        "name": "6. Two-Step Leave Application Flow (Step 1: Proposal)",
        "employee_id": "EMP-001",
        "session_id": "eval-session-6",
        "message": "I want to take 2 days of annual leave next Thursday and Friday.",
        "expected_route": "tool",
    },
]


def run_eval(base_url: str) -> None:
    print("=" * 80)
    print(f"Executing Veltrix Evaluation Suite against {base_url}")
    print("=" * 80)

    # First check /health
    try:
        health_resp = httpx.get(f"{base_url}/health", timeout=10.0)
        print(f"Health check status: {health_resp.status_code} -> {health_resp.text}")
        if health_resp.status_code != 200:
            print("Server is not healthy yet. Exiting.")
            sys.exit(1)
    except Exception as e:
        print(f"Failed to connect to {base_url}/health: {e}")
        print(
            "Ensure the FastAPI server is running (`uv run uvicorn veltrix.api.main:app --port 8000`)."
        )
        sys.exit(1)

    for item in QUERIES:
        print("\n" + "-" * 70)
        print(f"Query: {item['name']}")
        print(f"As: {item['employee_id']} | Message: '{item['message']}'")

        headers = {
            "X-Employee-Id": item["employee_id"],
            "Content-Type": "application/json",
        }
        payload = {
            "session_id": item["session_id"],
            "message": item["message"],
        }

        try:
            resp = httpx.post(f"{base_url}/chat", json=payload, headers=headers, timeout=30.0)
            print(f"HTTP Status: {resp.status_code}")
            data = resp.json()
            print(f"Route: {data.get('route')}")
            print(f"Citations: {data.get('citations')}")
            print(f"Awaiting Confirmation: {data.get('awaiting_confirmation')}")
            print("Response Content:")
            print(data.get("content"))
        except Exception as ex:
            print(f"Request failed: {ex}")

    print("\n" + "=" * 80)
    print("Evaluation Suite Run Completed.")
    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Veltrix Assistant endpoints.")
    parser.add_argument(
        "--base-url", type=str, default="http://localhost:8000", help="Service base URL"
    )
    args = parser.parse_args()

    run_eval(args.base_url)


if __name__ == "__main__":
    main()
