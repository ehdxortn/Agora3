from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Confidence(str, Enum):
    REJECTED = "REJECTED"
    WEAK = "WEAK"
    CANDIDATE = "CANDIDATE"
    ROBUST_CANDIDATE = "ROBUST_CANDIDATE"
    PRODUCTION_CANDIDATE = "PRODUCTION_CANDIDATE"


FEATURE_COLUMN_CATALOG: dict[str, tuple[str, ...]] = {
    "oi_change": ("oi_close", "oi_value_close"),
    "oi_zscore": ("oi_close", "oi_value_close"),
    "funding_mean": ("funding_rate",),
    "funding_zscore": ("funding_rate",),
    "taker_imbalance": ("taker_log_imbalance_mean", "taker_ls_close"),
    "ls_ratio_zscore": (
        "global_account_ls_close",
        "toptrader_account_ls_close",
        "toptrader_position_ls_close",
    ),
    "onchain_zscore": (
        "tx_count",
        "block_count",
        "fees_btc",
        "gross_output_btc",
        "mean_fee_sat_vb",
        "median_fee_sat_vb",
        "active_addresses",
        "hash_rate",
    ),
}

DEFAULT_FEATURE_COLUMN: dict[str, str] = {
    "oi_change": "oi_value_close",
    "oi_zscore": "oi_value_close",
    "funding_mean": "funding_rate",
    "funding_zscore": "funding_rate",
    "taker_imbalance": "taker_log_imbalance_mean",
    "ls_ratio_zscore": "global_account_ls_close",
    "onchain_zscore": "active_addresses",
}


class FeatureSpec(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    family: Literal[
        "price_return", "ema_gap", "rsi", "atr_pct", "realized_vol",
        "volume_zscore", "oi_change", "oi_zscore", "funding_mean",
        "funding_zscore", "taker_imbalance", "ls_ratio_zscore", "onchain_zscore",
    ]
    lookback: int = Field(default=14, ge=1, le=720)
    column: str | None = None
    fast: int | None = Field(default=None, ge=1, le=720)
    slow: int | None = Field(default=None, ge=2, le=1440)

    @model_validator(mode="after")
    def validate_data_capability(self):
        allowed = FEATURE_COLUMN_CATALOG.get(self.family)
        if not allowed:
            return self
        column = self.column or DEFAULT_FEATURE_COLUMN[self.family]
        if column not in allowed:
            raise ValueError(
                f"Feature family {self.family} cannot use column {column!r}; "
                f"available columns are {', '.join(allowed)}"
            )
        return self


class ConditionSpec(BaseModel):
    feature: str
    op: Literal["gt", "gte", "lt", "lte"]
    threshold_type: Literal["absolute", "train_quantile"] = "absolute"
    value: float

    @model_validator(mode="after")
    def quantile_bounds(self):
        if self.threshold_type == "train_quantile" and not 0 < self.value < 1:
            raise ValueError("train_quantile value must be between 0 and 1")
        return self


class ExitSpec(BaseModel):
    mode: Literal["fixed_horizon", "stop_target"] = "fixed_horizon"
    horizon_bars: int = Field(default=3, ge=1, le=42)
    stop_loss_pct: float | None = Field(default=None, gt=0, le=0.5)
    take_profit_pct: float | None = Field(default=None, gt=0, le=2)

    @model_validator(mode="after")
    def stop_target_requires_both(self):
        if self.mode == "stop_target" and (self.stop_loss_pct is None or self.take_profit_pct is None):
            raise ValueError("stop_target requires stop and target")
        return self


class ExperimentSpec(BaseModel):
    hypothesis: str = Field(min_length=20, max_length=2000)
    mechanism: str = Field(min_length=20, max_length=4000)
    side: Literal["long", "short"]
    features: list[FeatureSpec] = Field(min_length=1, max_length=12)
    conditions: list[ConditionSpec] = Field(min_length=1, max_length=12)
    exit: ExitSpec = Field(default_factory=ExitSpec)
    train_fraction: float = Field(default=0.60, ge=0.4, le=0.8)
    validation_fraction: float = Field(default=0.20, ge=0.1, le=0.3)
    embargo_bars: int = Field(default=6, ge=0, le=84)
    fee_bps: float = Field(default=8, ge=0, le=100)
    slippage_bps: float = Field(default=2, ge=0, le=100)
    source_research_ids: list[str] = Field(default_factory=list, max_length=30)
    novelty_note: str = ""

    @model_validator(mode="after")
    def validate_contract(self):
        if self.train_fraction + self.validation_fraction >= 0.95:
            raise ValueError("Need at least 5% sealed holdout data")
        names = {f.name for f in self.features}
        missing = [c.feature for c in self.conditions if c.feature not in names]
        if missing:
            raise ValueError(f"Undefined features: {missing}")
        return self


class SplitMetrics(BaseModel):
    observations: int = 0
    trades: int = 0
    win_rate: float | None = None
    mean_net_return: float | None = None
    median_net_return: float | None = None
    profit_factor: float | None = None
    max_drawdown: float | None = None
    cumulative_return: float | None = None
    sharpe_like: float | None = None


class ExperimentResult(BaseModel):
    experiment_id: str
    spec_hash: str
    train: SplitMetrics
    validation: SplitMetrics
    # None means the chronological final holdout is sealed. No observations, signal counts,
    # feature distributions, or outcomes from that segment are exposed during exploration.
    test: SplitMetrics | None = None
    parameter_stability: dict[str, Any] = Field(default_factory=dict)
    pre_holdout_robustness: dict[str, Any] = Field(default_factory=dict)
    cost_stress: dict[str, Any] = Field(default_factory=dict)
    methodological_flags: list[str] = Field(default_factory=list)
    passed_minimum_gate: bool = False
    holdout_revealed: bool = False
    gate_basis: Literal["validation", "test"] = "validation"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LiteratureItem(BaseModel):
    title: str
    url: str
    source_type: Literal[
        "peer_reviewed", "preprint", "institutional", "exchange", "github",
        "blog", "interview", "other",
    ]
    quality_tier: Literal["A", "B", "C"]
    published_date: str | None = None
    research_question: str
    claim: str
    method: str
    dataset_period: str | None = None
    timeframe: str | None = None
    costs_included: bool | None = None
    leakage_risks: list[str] = Field(default_factory=list)
    replication_value: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    tags: list[str] = Field(default_factory=list)

    @field_validator("leakage_risks", "tags", mode="before")
    @classmethod
    def normalize_lists(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"none", "n/a", "na", "null", "unknown"}:
                return []
            return [text]
        return [str(value)]

    @field_validator("costs_included", mode="before")
    @classmethod
    def normalize_costs(cls, value):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if not text or text in {"null", "none", "n/a", "na", "unknown", "unclear"}:
                return None
            unknown = ("not reported", "not stated", "not specified", "does not report", "does not state", "does not specify", "does not detail", "cannot determine", "insufficient information")
            if any(x in text for x in unknown):
                return None
            false_values = ("no explicit", "not included", "excluded", "ignores transaction", "without transaction", "before costs", "gross return", "gross returns", "no transaction cost", "no trading cost")
            if any(x in text for x in false_values):
                return False
            true_values = ("after costs", "net of costs", "net-of-cost", "transaction costs included", "trading costs included", "fees included", "accounts for transaction", "includes transaction")
            if any(x in text for x in true_values):
                return True
        return None


class LiteratureBatch(BaseModel):
    items: list[LiteratureItem] = Field(min_length=1, max_length=12)


class LiteratureMap(BaseModel):
    themes: list[str] = Field(default_factory=list, max_length=8)
    replicated_findings: list[str] = Field(default_factory=list, max_length=8)
    contradictions: list[str] = Field(default_factory=list, max_length=8)
    weak_or_invalid_claims: list[str] = Field(default_factory=list, max_length=8)
    high_value_replications: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


class CriticReview(BaseModel):
    verdict: Literal["PASS", "CHALLENGE", "FAIL"]
    fatal_objections: list[str] = Field(default_factory=list, max_length=12)
    nonfatal_objections: list[str] = Field(default_factory=list, max_length=12)
    required_tests: list[str] = Field(default_factory=list, max_length=12)
    assessment: str = Field(min_length=1, max_length=6000)


class DirectorDecision(BaseModel):
    research_status: Literal["CONTINUE", "COMPLETE", "BLOCKED"]
    confidence: Confidence
    interpretation: str
    critic_questions: list[str] = Field(default_factory=list)
    research_directive: str = ""
    next_action: Literal["LITERATURE", "REPLICATION", "EXPERIMENT", "ROBUSTNESS", "PROMOTE", "STOP"]
    next_experiment: ExperimentSpec | None = None
    reason_for_next_action: str


class PromotionPackage(BaseModel):
    contract_version: Literal["1.0"] = "1.0"
    research_run_id: str
    experiment_id: str
    signal_name: str
    asset: Literal["BTC"] = "BTC"
    timeframe: Literal["4h"] = "4h"
    decision_time: Literal["candle_close"] = "candle_close"
    entry_time: Literal["next_candle_open"] = "next_candle_open"
    experiment_spec: ExperimentSpec
    validated_metrics: ExperimentResult
    feature_contract: dict[str, Any]
    execution_contract: dict[str, Any]
    data_contract: dict[str, Any]
    resolved_thresholds: dict[str, float]
    parity_fixture: dict[str, Any]
    code_version: str
    prompt_version: str
    status: Literal["PENDING_PARITY", "PARITY_PASSED", "SHADOW_APPROVED", "REJECTED"] = "PENDING_PARITY"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ParitySubmission(BaseModel):
    vectors: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    relative_tolerance: float = Field(default=1e-10, gt=0, le=1e-4)


class StartRunRequest(BaseModel):
    mission: str = (
        "Discover repeatable, causal, economically exploitable Bitcoin trading edges that "
        "remain positive after realistic fees and slippage and survive chronological "
        "out-of-sample validation."
    )
    budget_usd: float | None = Field(default=None, gt=0, le=1000)
    notes: str = ""
