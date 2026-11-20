# 개념 레지스트리

투자자산운용사 개념을 층을 만들 때 그 층에 필요한 것만 등록한다([PRD](../../PRD.md) 10절). 미리 전부 정리하지 않고, 구현하는 작업에서 끌어온다(pull).

- 등록 목록: [`config/concepts.toml`](../../config/concepts.toml)
- `status = "implemented"`인 개념은 모듈이 import되고, 테스트 파일과 카드가 있어야 한다. `tests/test_concept_registry.py`가 이를 강제한다.
- 카드 하나는 개념 하나다. 카드에는 **정의, 공식, 구현 위치, 교재와 다른 점(근사·가정)**을 적는다.

## 구현된 개념

| ID | 개념 | 분류 | 카드 |
|---|---|---|---|
| `total_return_index` | 총수익 지수 | 투자운용결과분석 | [total_return_index.md](total_return_index.md) |
| `monthly_return` | 월간 총수익률 | 투자운용결과분석 | [monthly_return.md](monthly_return.md) |
| `cash_proxy_dtb3` | 현금 수익률 대용(DTB3) | 분산투자기법 | [cash_proxy_dtb3.md](cash_proxy_dtb3.md) |
| `volatility` | 변동성 | 리스크관리 | [volatility.md](volatility.md) |
| `max_drawdown` | 최대낙폭 | 리스크관리 | [max_drawdown.md](max_drawdown.md) |
| `historical_var` | 역사적 VaR | 리스크관리 | [historical_var.md](historical_var.md) |
| `correlation` | 상관계수 | 분산투자기법 | [correlation.md](correlation.md) |
| `risk_contribution` | 위험기여도 | 분산투자기법 | [risk_contribution.md](risk_contribution.md) |
| `strategic_allocation` | 전략적 자산배분과 리밸런싱 | 분산투자기법 | [strategic_allocation.md](strategic_allocation.md) |
| `cagr_calmar` | 연복리수익률과 칼마 비율 | 투자운용결과분석 | [cagr_calmar.md](cagr_calmar.md) |
| `sharpe_ratio` | 샤프 비율 | 투자운용결과분석 | [sharpe_ratio.md](sharpe_ratio.md) |
| `sortino_ratio` | 소르티노 비율 | 투자운용결과분석 | [sortino_ratio.md](sortino_ratio.md) |
| `information_ratio` | 정보비율과 추적오차 | 투자운용결과분석 | [information_ratio.md](information_ratio.md) |
| `mean_variance` | 평균-분산(최소분산 포트폴리오) | 분산투자기법 | [mean_variance.md](mean_variance.md) |
| `macro_first_release` | 거시 지표의 최초 발표값 | 거시경제분석 | [macro_first_release.md](macro_first_release.md) |
| `regime_rules` | 경기 국면 규칙 | 거시경제분석 | [regime_rules.md](regime_rules.md) |
| `macro_market_context` | 금리·달러 맥락 | 거시경제분석 | [macro_market_context.md](macro_market_context.md) |
| `regime_performance` | 국면별 과거 성과 | 투자운용결과분석 | [regime_performance.md](regime_performance.md) |
| `prediction_scoring` | 예측과 채점 | 투자운용결과분석 | [prediction_scoring.md](prediction_scoring.md) |

## 등록 예정

[로드맵](../roadmap.md) 2절에 있다. 구현하는 작업에서 등록하고 카드를 만든다.
