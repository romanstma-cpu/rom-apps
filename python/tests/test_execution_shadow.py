import execution_shadow


T = 1_800_000_000.0


def rows(count=520):
    output = []
    for i in range(count):
        clean = i % 4 in (0, 1, 2)
        output.append({
            "at": T + i * 7200,
            "local_id": f"L{i}",
            "ticker": f"M{i}",
            "quantity": 10,
            "limit_price": .60,
            "source": "momentum" if i % 2 else "whale",
            "style": "maker" if clean else "crossing",
            "signal_cents": 59,
            "bid_cents": 59 if clean else 56,
            "ask_cents": 60,
            "response_ms": 75 if clean else 900,
            "features": {
                "bidDepth3": 100 if clean else 5,
                "askDepth3": 80 if clean else 100,
                "bookImbalance3": .11 if clean else -.90,
                "quoteAgeMs": 50 if clean else 1800,
            },
            "filled": int(clean),
            "adverse": int(not clean),
        })
    return output


def test_execution_models_beat_constant_baselines_on_later_data():
    report = execution_shadow.fit(rows(), T + 521 * 7200)["report"]
    assert report["controlsLiveTrading"] is False
    assert report["fillModel"]["status"] == "promising"
    assert report["adverseModel"]["status"] == "promising"
    assert report["fillModel"]["modelBrier"] < report["fillModel"]["baselineBrier"]
    assert report["adverseModel"]["modelLogLoss"] < report["adverseModel"]["baselineLogLoss"]


def test_execution_models_require_chronological_evidence():
    report = execution_shadow.fit(rows(30), T + 31 * 7200)["report"]
    assert report["status"] == "collecting"
    assert report["fillModel"]["modelBrier"] is None
    assert report["adverseModel"]["modelBrier"] is None


def test_later_rows_cannot_change_an_earlier_report():
    evidence = rows()
    cutoff = T + 300 * 7200
    expected = execution_shadow.fit(evidence, cutoff)
    for row in evidence:
        if row["at"] >= cutoff:
            row["filled"] = 1 - row["filled"]
            row["adverse"] = 1 - row["adverse"]
    assert execution_shadow.fit(evidence, cutoff) == expected
