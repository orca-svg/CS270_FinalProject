# 풍선 / 표적 예측

`gesture_bt/balloon_intercept.py`는 리드샷 조준에 `ParabolicTracker`를 사용한다.
예측기는 연속된 표적 중심점에서 수평 속도, 수직 속도, 수직 가속도를 추정한다.

## 모델

표적 중심 `(x, y)`와 예측 시간 `t`에 대해:

```text
pred_x = x + vx * t
pred_y = y + vy * t + 0.5 * ay * t^2
```

`vx`, `vy`, `ay`는 EMA로 완화해 HSV 탐지 노이즈가 조준점에 바로 튀지 않도록 한다.

## CLI 옵션

| 옵션 | 의미 |
|------|------|
| `--flight-time` | 발사체 도달 예상 시간(초) |
| `--lead-frames` | `flight-time`에 추가할 프레임 기반 리드 |
| `--velocity-smoothing` | `vx`, `vy` EMA 계수 |
| `--accel-smoothing` | 수직 가속도 EMA 계수 |

실제 예측 시간은 다음과 같다.

```text
lead_time = flight_time + lead_frames * last_frame_dt
```

## 캘리브레이션 작업

예측 로직은 구현되어 있지만 `flight_time`과 시스템 지연은 실제 장비로 보정해야
한다. P4/P5는 실험 영상 또는 CSV 로그를 남기고 명중/실패 및 예측 오차를 기준으로
상수를 조정한다.
