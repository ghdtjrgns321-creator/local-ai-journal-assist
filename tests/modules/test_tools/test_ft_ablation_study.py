"""FT-T Ablation Study 스크립트 — 분류 로직 단위 테스트."""

from __future__ import annotations

from tools.scripts.ft_ablation_study import classify_conclusion, write_report


class TestClassifyConclusion:
    def test_keep_when_ft_helps(self):
        # Why: Δ +1% 이상이면 유지
        assert classify_conclusion(0.82, 0.80) == "keep"

    def test_remove_when_ft_hurts(self):
        # Why: Δ -1%면 제거 검토
        assert classify_conclusion(0.79, 0.80) == "remove"

    def test_inconclusive_within_noise(self):
        # Why: Δ < 0.5%는 노이즈 범위
        assert classify_conclusion(0.802, 0.800) == "inconclusive"

    def test_exact_threshold_is_keep(self):
        # 경계값 테스트 — 정확히 threshold면 keep
        assert classify_conclusion(0.805, 0.800) == "keep"


class TestWriteReport:
    def test_report_generated(self, tmp_path):
        path = tmp_path / "report.md"
        fake = {
            "8_model_f1": 0.812,
            "7_model_f1": 0.808,
            "delta_f1": 0.004,
            "delta_relative_pct": 0.49,
            "conclusion": "inconclusive",
            "n_samples": 50_000,
            "n_fraud": 1_200,
        }
        write_report(fake, output_path=path)
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "0.812" in text
        assert "50,000" in text
        assert "판정 보류" in text
