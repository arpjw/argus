use argus::checkpoint::{ArgusCheckpoint, RegimeAssessment, SignalRecord};

fn make_regime(class: &str, seq: u64) -> RegimeAssessment {
    RegimeAssessment {
        regime_class: class.to_string(),
        confidence: 0.7,
        horizon_days: 3,
        produced_at: 1000,
        session_id: "s1".to_string(),
        model_version: "v1".to_string(),
        wal_sequence: seq,
    }
}

fn make_signal(id: &str, expires_at: u64) -> SignalRecord {
    SignalRecord {
        id: id.to_string(),
        market_id: "BTC-USDC".to_string(),
        direction: "long".to_string(),
        magnitude: 0.3,
        conviction: "medium".to_string(),
        expires_at,
        produced_at: 1000,
        regime_source: "risk_on_growth".to_string(),
        wal_sequence: 1,
        published: false,
    }
}

#[test]
fn test_regime_history_capped_at_10() {
    let mut cp = ArgusCheckpoint::new("s1".to_string());
    for i in 0..15u64 {
        cp.apply_regime_assessment(make_regime("neutral_drift", i));
    }
    assert_eq!(cp.regime_history.len(), 10);
    assert_eq!(cp.inferences_run_total, 15);
}

#[test]
fn test_regime_history_order() {
    let mut cp = ArgusCheckpoint::new("s1".to_string());
    for i in 0..12u64 {
        cp.apply_regime_assessment(make_regime("neutral_drift", i));
    }
    // oldest entries evicted; back should be most recent
    assert_eq!(cp.regime_history.back().unwrap().wal_sequence, 11);
    assert_eq!(cp.regime_history.front().unwrap().wal_sequence, 2);
}

#[test]
fn test_signal_stored_correctly() {
    let mut cp = ArgusCheckpoint::new("s1".to_string());
    cp.apply_signal_produced(make_signal("sig1", 9999999999));
    assert_eq!(cp.active_signals.len(), 1);
    assert_eq!(cp.signals_produced_total, 1);
    assert!(cp.active_signals.contains_key("sig1"));
}

#[test]
fn test_purge_expired_signals() {
    let mut cp = ArgusCheckpoint::new("s1".to_string());
    // Far future: keep
    cp.apply_signal_produced(make_signal("live", 9_999_999_999_999));
    // Already expired (1 ms)
    cp.apply_signal_produced(make_signal("dead", 1));

    cp.purge_expired_signals();

    assert_eq!(cp.active_signals.len(), 1);
    assert!(cp.active_signals.contains_key("live"));
    assert!(!cp.active_signals.contains_key("dead"));
}

#[test]
fn test_latest_regime() {
    let mut cp = ArgusCheckpoint::new("s1".to_string());
    assert!(cp.latest_regime().is_none());

    cp.apply_regime_assessment(make_regime("risk_on_growth", 1));
    cp.apply_regime_assessment(make_regime("deflation_risk", 2));

    let latest = cp.latest_regime().unwrap();
    assert_eq!(latest.regime_class, "deflation_risk");
    assert_eq!(latest.wal_sequence, 2);
}
