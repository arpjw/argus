use argus::fsm::{ArgusEvent, ArgusFsm, ArgusState};
use argus::wal::ArgusWal;
use std::sync::Arc;
use tempfile::TempDir;

async fn make_fsm(dir: &std::path::Path) -> ArgusFsm {
    let wal = Arc::new(ArgusWal::open(dir).await.unwrap());
    ArgusFsm::new(wal, "test-session".to_string())
}

#[tokio::test]
async fn test_happy_path_transitions() {
    let dir = TempDir::new().unwrap();
    let mut fsm = make_fsm(dir.path()).await;

    assert_eq!(fsm.state, ArgusState::Idle);

    fsm.transition(ArgusEvent::Start).await.unwrap();
    assert_eq!(fsm.state, ArgusState::IngestingData);

    fsm.transition(ArgusEvent::AllSourcesIngested).await.unwrap();
    assert_eq!(fsm.state, ArgusState::RunningClassifier);

    fsm.transition(ArgusEvent::ClassificationComplete {
        regime: "neutral_drift".into(),
        confidence: 0.5,
    }).await.unwrap();
    assert_eq!(fsm.state, ArgusState::RunningGenerative);

    fsm.transition(ArgusEvent::GenerativeComplete).await.unwrap();
    assert_eq!(fsm.state, ArgusState::ProducingSignals);

    fsm.transition(ArgusEvent::SignalsProduced { count: 0 }).await.unwrap();
    assert_eq!(fsm.state, ArgusState::PublishingSignals);

    fsm.transition(ArgusEvent::SignalsPublished).await.unwrap();
    assert_eq!(fsm.state, ArgusState::WaitingForNextTick);

    fsm.transition(ArgusEvent::TickElapsed).await.unwrap();
    assert_eq!(fsm.state, ArgusState::IngestingData);
}

#[tokio::test]
async fn test_ingest_error_stays_in_ingesting() {
    let dir = TempDir::new().unwrap();
    let mut fsm = make_fsm(dir.path()).await;
    fsm.transition(ArgusEvent::Start).await.unwrap();
    assert_eq!(fsm.state, ArgusState::IngestingData);

    fsm.transition(ArgusEvent::IngestError {
        source: "FRED".into(),
        error: "no key".into(),
    }).await.unwrap();
    assert_eq!(fsm.state, ArgusState::IngestingData);
}

#[tokio::test]
async fn test_inference_error_goes_to_producing_signals() {
    let dir = TempDir::new().unwrap();
    let mut fsm = make_fsm(dir.path()).await;
    fsm.transition(ArgusEvent::Start).await.unwrap();
    fsm.transition(ArgusEvent::AllSourcesIngested).await.unwrap();
    assert_eq!(fsm.state, ArgusState::RunningClassifier);

    fsm.transition(ArgusEvent::InferenceError {
        model: "m1".into(),
        error: "oom".into(),
    }).await.unwrap();
    assert_eq!(fsm.state, ArgusState::ProducingSignals);
}

#[tokio::test]
async fn test_stop_from_any_state() {
    let dir = TempDir::new().unwrap();

    let states = vec![
        ArgusState::Idle,
        ArgusState::IngestingData,
        ArgusState::RunningClassifier,
        ArgusState::WaitingForNextTick,
    ];

    for initial in states {
        let wal = Arc::new(ArgusWal::open(dir.path()).await.unwrap());
        let mut fsm = ArgusFsm::new(wal, "test".to_string());
        fsm.state = initial;
        fsm.transition(ArgusEvent::Stop).await.unwrap();
        assert_eq!(fsm.state, ArgusState::Stopping);
    }
}

#[tokio::test]
async fn test_pause_and_resume() {
    let dir = TempDir::new().unwrap();
    let mut fsm = make_fsm(dir.path()).await;
    fsm.transition(ArgusEvent::Start).await.unwrap();
    assert_eq!(fsm.state, ArgusState::IngestingData);

    fsm.transition(ArgusEvent::Pause).await.unwrap();
    assert_eq!(fsm.state, ArgusState::Paused);

    fsm.transition(ArgusEvent::Resume).await.unwrap();
    assert_eq!(fsm.state, ArgusState::Idle);
}
