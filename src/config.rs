use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArgusConfig {
    pub session_dir: PathBuf,
    pub data_sources: Vec<String>,
    pub classifier_id: Vec<String>,
    pub publisher: String,
    pub output_path: Option<PathBuf>,
    pub tick_interval_ms: u64,
    pub checkpoint_interval_ticks: u64,
    pub norgate_data_dir: Option<PathBuf>,
    pub markets: Vec<String>,
}

impl Default for ArgusConfig {
    fn default() -> Self {
        Self {
            session_dir: dirs::home_dir()
                .unwrap()
                .join(".argus/sessions/default"),
            data_sources: vec!["KALSHI".to_string()],
            classifier_id: vec!["argus-placeholder".to_string()],
            publisher: "stdout".to_string(),
            output_path: None,
            tick_interval_ms: 60_000,
            checkpoint_interval_ticks: 5,
            norgate_data_dir: None,
            markets: vec![
                "BTC-USDC".to_string(),
                "ETH-USDC".to_string(),
                "SOL-USDC".to_string(),
            ],
        }
    }
}

impl ArgusConfig {
    pub fn from_file(path: &Path) -> anyhow::Result<Self> {
        let data = std::fs::read_to_string(path)?;
        let config: Self = serde_json::from_str(&data)?;
        Ok(config)
    }

    pub fn validate(&self) -> anyhow::Result<()> {
        if self.tick_interval_ms == 0 {
            anyhow::bail!("tick_interval_ms must be > 0");
        }
        if self.data_sources.is_empty() {
            anyhow::bail!("at least one data_source required");
        }
        Ok(())
    }
}
