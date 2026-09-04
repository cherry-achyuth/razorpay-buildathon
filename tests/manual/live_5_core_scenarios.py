"""Verification script for the 5 Core Demo Scenarios."""

import httpx

def run_live_verification():
    client = httpx.Client(base_url="http://127.0.0.1:8000")

    print("=" * 65)
    print("DECISIONVAULT LIVE 5 CORE DEMO SCENARIOS VERIFICATION")
    print("=" * 65)

    # Step 1: Clean Demo Seeding
    seed_res = client.post("/api/v1/demo/seed")
    assert seed_res.status_code == 200
    print("[+] Database Cleaned & Seeded Fresh")

    u_res = client.get("/api/v1/users")
    user_id = u_res.json()["users"][0]["id"]

    m_res = client.get("/api/v1/merchants")
    merchants = m_res.json()["merchants"]
    print(f"[+] Verified Merchants Count: {len(merchants)}")
    for m in merchants:
        print(f"    - {m['name']} ({m['external_reference']})")

    # 1. Usual Subscription
    s1 = client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay my usual Netflix subscription",
            "currency": "INR",
            "auto_execute_payment": False,
        },
    ).json()
    print("\n[Scenario 1] 'Pay my usual Netflix subscription'")
    print("  Decision:", s1["decision"])
    print(
        "  Resolved:",
        s1["structured_intent"]["merchant_name"],
        "->",
        s1["structured_intent"]["amount"],
        s1["structured_intent"]["currency"],
    )
    print("  Note:    ", s1["structured_intent"]["resolution_notes"])
    assert s1["decision"] == "ALLOW"
    assert float(s1["structured_intent"]["amount"]) == 649.00

    # 2. Price Drift Anomaly
    s2 = client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 1500 INR to Netflix",
            "currency": "INR",
            "auto_execute_payment": False,
        },
    ).json()
    print("\n[Scenario 2] 'Pay 1500 INR to Netflix'")
    print("  Decision:", s2["decision"])
    print("  Reason:  ", s2.get("decision_details", {}).get("reason"))
    assert s2["decision"] == "ASK_USER"

    # 3. New Merchant Guard
    s3 = client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Order food from Swiggy Instamart",
            "currency": "INR",
            "auto_execute_payment": False,
        },
    ).json()
    print("\n[Scenario 3] 'Order food from Swiggy Instamart'")
    print("  Decision:", s3["decision"])
    print(
        "  Merchant:",
        s3["structured_intent"]["merchant_name"],
        f"(is_new={s3['structured_intent']['is_new_merchant']})",
    )
    assert s3["decision"] == "ASK_USER"

    # 4. Comparison Table
    s4 = client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Compare Netflix vs Amazon Prime for a year",
            "currency": "INR",
            "auto_execute_payment": False,
        },
    ).json()
    print("\n[Scenario 4] 'Compare Netflix vs Amazon Prime for a year'")
    print("  Decision:        ", s4["decision"])
    print("  Comparison Rows: ", len(s4.get("comparison_data", [])))
    for row in s4.get("comparison_data", []):
        print(f"    - {row['name']}: Rs. {row.get('estimated_annual_inr', 0)}/yr")
    assert len(s4.get("comparison_data", [])) >= 2

    # 5. Hard Cap & Unverified
    s5 = client.post(
        "/api/v1/agent/evaluate",
        json={
            "user_id": user_id,
            "prompt": "Pay 5000 INR to Unknown Shady Mart",
            "currency": "INR",
            "auto_execute_payment": False,
        },
    ).json()
    print("\n[Scenario 5] 'Pay 5000 INR to Unknown Shady Mart'")
    print("  Decision:", s5["decision"])
    print("  Reason:  ", s5.get("decision_details", {}).get("reason"))
    assert s5["decision"] == "BLOCK"

    print("\n" + "=" * 65)
    print("ALL 5 SCENARIOS ARE BULLETPROOF AND READY FOR DEMO!")
    print("=" * 65)


if __name__ == "__main__":
    run_live_verification()
