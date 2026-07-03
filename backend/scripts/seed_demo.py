"""Seed the Ahmedabad-CA-firms demo workspace.

Thin CLI wrapper around ``app.seeds.demo.seed_demo``. Idempotent — safe to run
repeatedly. Prints the achieved funnel distribution.

    uv run python -m scripts.seed_demo
"""

from __future__ import annotations

import sys

from app.seeds.demo import seed_demo


def main() -> int:
    totals = seed_demo()
    ct = totals.get("total_contacts", 0) or 1
    print("Demo workspace seeded.")
    print(f"  tenant_id       {totals.get('tenant_id')}")
    print(f"  job_id          {totals.get('job_id')}")
    print(f"  companies       {totals.get('total_companies')}")
    print(f"  contacts        {totals.get('total_contacts')}")
    print(
        f"  emails found    {totals.get('emails_found')} "
        f"({round(100 * totals.get('emails_found', 0) / ct, 1)}% of contacts)"
    )
    print(f"  verified        {totals.get('verified_emails')}")
    print(f"  review          {totals.get('review_emails')}")
    print(f"  invalid         {totals.get('invalid_emails')}")
    print(f"  sales-ready     {totals.get('sales_ready_count')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
