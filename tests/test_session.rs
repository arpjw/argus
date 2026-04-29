use argus::config::ArgusConfig;
use argus::fsm::ArgusEvent;
use argus::session::ArgusSession;
use argus::wal::{ArgusWal, SESSION_START, SESSION_STOP, CHECKPOINT, INFERENCE_COMPLETED};
use tempfile::TempDir;

fn fast_config(dir: &std::path::Path) -> ArgusConfig {
    ArgusConfig {
        session_dir: dir.to_path_buf(),
        data_sources: vec!["KALSHI".to_string()],
        classifier_id: vec!["argus-placeholder".to_string()],
        publisher: "stdout".to_string(),
        output_path: None,
        tick_interval_ms: 1,
        checkpoint_interval_ticks: 2,
        norgate_data_dir: None,
        markets: vec!["BTC-USDC".to_string()],
    }
}

#[tokio::test]
async fn test_session_start_writes_session_start_wal_entry() {
    let dir = TempDir::new().unwrap();
    let _session = ArgusSession::new(fast_config(dir.path())).await.unwrap();

    let seg = dir.path().join("argus_wal_0000.log");
    let entries = ArgusWal::read_from(&seg, 0).unwrap();
    assert!(!entries.is_empty());
    assert_eq!(entries[0].entry_type, SESSION_START);
}

#[tokio::test]
async fn test_session_run_two_ticks() {
    let dir = TempDir::new().unwrap();
    let config = fast_config(dir.path());
    let mut session = ArgusSession::new(config).await.unwrap();

    let handle = tokio::spawn(async move {
        session.run().await
    });

    // Let it run for 100ms (enough for 2 ticks at 1ms)
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
    // The session loops indefinitely until Stop; we just verify it runs without panicking
    // then cancel via task abort
    handle.abort();
    let _ = handle.await;

    let seg = dir.path().join("argus_wal_0000.log");
    let entries = ArgusWal::read_from(&seg, 0).unwrap();
    let types: Vec<u32> = entries.iter().map(|e| e.entry_type).collect();

    // Must have written SESSION_START
    assert!(types.contains(&SESSION_START));
    // Must have written at least one INFERENCE_COMPLETED (from classifier)
    assert!(types.contains(&INFERENCE_COMPLETED));
}

#[tokio::test]
async fn test_checkpoint_written_after_interval() {
    let dir = TempDir::new().unwrap();
    let mut config = fast_config(dir.path());
    config.checkpoint_interval_ticks = 1;

    let mut session = ArgusSession::new(config).await.unwrap();

    let handle = tokio::spawn(async move {
        session.run().await
    });

    tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
    handle.abort();
    let _ = handle.await;

    let seg = dir.path().join("argus_wal_0000.log");
    let entries = ArgusWal::read_from(&seg, 0).unwrap();
    let has_checkpoint = entries.iter().any(|e| e.entry_type == CHECKPOINT);
    assert!(has_checkpoint, "expected at least one CHECKPOINT WAL entry");
}

#[tokio::test]
async fn test_clean_shutdown_writes_session_stop() {
    let dir = TempDir::new().unwrap();
    let config = fast_config(dir.path());
    let mut session = ArgusSession::new(config).await.unwrap();

    // Signal stop after a tick
    tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
    session.fsm.transition(ArgusEvent::Stop).await.unwrap();
    session.run().await.unwrap();

    let seg = dir.path().join("argus_wal_0000.log");
    let entries = ArgusWal::read_from(&seg, 0).unwrap();
    let has_stop = entries.iter().any(|e| e.entry_type == SESSION_STOP);
    assert!(has_stop, "expected SESSION_STOP WAL entry after clean shutdown");
}
