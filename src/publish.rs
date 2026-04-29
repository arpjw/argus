use std::path::PathBuf;

use async_trait::async_trait;
use tokio::io::AsyncWriteExt;

use crate::checkpoint::SignalRecord;

#[async_trait]
pub trait SignalPublisher: Send + Sync {
    async fn publish(&self, signals: &[SignalRecord]) -> anyhow::Result<()>;
    fn publisher_id(&self) -> &str;
}

pub struct StdoutPublisher;

#[async_trait]
impl SignalPublisher for StdoutPublisher {
    async fn publish(&self, signals: &[SignalRecord]) -> anyhow::Result<()> {
        println!("{}", serde_json::to_string_pretty(signals)?);
        Ok(())
    }

    fn publisher_id(&self) -> &str {
        "stdout"
    }
}

pub struct FilePublisher {
    pub output_path: PathBuf,
}

#[async_trait]
impl SignalPublisher for FilePublisher {
    async fn publish(&self, signals: &[SignalRecord]) -> anyhow::Result<()> {
        let mut file = tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.output_path)
            .await?;
        for signal in signals {
            let line = serde_json::to_string(signal)?;
            file.write_all(line.as_bytes()).await?;
            file.write_all(b"\n").await?;
        }
        file.flush().await?;
        Ok(())
    }

    fn publisher_id(&self) -> &str {
        "file"
    }
}

pub struct MonolithStrategyPublisher {
    pub endpoint: String,
    pub api_key: String,
}

#[async_trait]
impl SignalPublisher for MonolithStrategyPublisher {
    async fn publish(&self, _signals: &[SignalRecord]) -> anyhow::Result<()> {
        anyhow::bail!("MonolithStrategyPublisher not yet implemented — use stdout or file")
    }

    fn publisher_id(&self) -> &str {
        "monolith_strategy_layer"
    }
}
