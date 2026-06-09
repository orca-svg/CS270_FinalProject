# 로컬 음성 인식 실행

`voice_commander_local.py`는 인터넷 음성 API 대신 노트북에서 Whisper를 실행한다.

- Apple Silicon macOS: `mlx-whisper`
- Windows: `faster-whisper` (`CPU int8` 기본 권장, NVIDIA CUDA 선택 가능)
- 공통 처리: 마이크 입력 -> RMS VAD -> Whisper -> 명령 분류 -> `control_mode.json`
- 카메라 루프와 음성 인식은 별도 프로세스로 실행하므로 음성 추론이 영상 프레임을 막지 않는다.
- 음성 프로세스는 시작·종료 시 `SAFE`, 2초 heartbeat, 발사 confidence 0.60을 적용한다.
- 카메라는 heartbeat가 10초 이상 끊기면 자동으로 `SAFE`로 전환한다.

상세 안전 정책은 [음성-BLE-Hub 안전성 보강 기록](VOICE_BLE_SAFETY.md)을 참고한다.

Whisper 모델은 저장소에 포함하지 않는다. 최초 실행 시 모델 저장소에서 자동 다운로드되며,
다음 실행부터 사용자 캐시를 재사용한다. macOS 기본 MLX 모델은
`mlx-community/whisper-base-mlx`, Windows 기본 모델은 `base`다.

## 1. macOS Apple Silicon

터미널을 열고 프로젝트 폴더로 이동한다.

```bash
cd "/Users/junyeop_lee/Desktop/kaist/2026_S/지로설/Final_project"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r gesture_bt/requirements_voice_mlx.txt
cd gesture_bt
```

마이크 번호를 확인하고 로컬 음성 인식을 실행한다.

```bash
python voice_commander_local.py --list-devices
python voice_commander_local.py --backend mlx --device-index 2 --language ko
```

시작 시 모델을 다운로드하고 짧은 무음으로 워밍업한다. `[LOCAL-STT] model ready` 이후
`옵티머스 발사`, `옵티머스 연발`, `옵티머스 멈춰`, `옵티머스 경계`처럼 말한다.
Whisper가 호출명을 영문 `Optimus`로 전사하는 경우도 같은 호출어로 처리한다.
호출어 없이 지연을 더 줄여 시험하려면 다음 명령을 사용한다.

```bash
python voice_commander_local.py --backend mlx --device-index 2 --language ko --no-wake-word
```

## 2. Windows 10/11

Python 3.11 또는 3.12의 64비트 버전을 권장한다. PowerShell에서 저장소 위치에 맞게
첫 번째 경로만 바꾼다.

```powershell
cd "C:\path\to\Final_project"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r gesture_bt\requirements_voice_windows.txt
cd gesture_bt
python voice_commander_local.py --list-devices
```

CPU에서 우선 검증한다.

```powershell
python voice_commander_local.py --backend faster-whisper --model base `
  --compute-device cpu --compute-type int8 --language ko
```

NVIDIA GPU 환경이 이미 준비된 경우에만 `--compute-device cuda`를 사용한다. CUDA/cuDNN
호환성 문제를 피하기 위해 최종 시연의 기준 경로는 CPU `int8`로 먼저 확정한다.

## 3. 카메라와 음성 병렬 실행

두 터미널 모두 `Final_project/gesture_bt`에서 실행한다.

터미널 1은 로봇 없이 카메라 인식을 검증한다.

```bash
# macOS
source ../.venv/bin/activate
python balloon_tracker_offline.py
```

```powershell
# Windows
..\.venv\Scripts\Activate.ps1
python balloon_tracker_offline.py
```

터미널 2는 로컬 음성 인식을 실행한다.

```bash
# macOS
source ../.venv/bin/activate
python voice_commander_local.py --backend mlx --language ko
```

```powershell
# Windows CPU
..\.venv\Scripts\Activate.ps1
python voice_commander_local.py --backend faster-whisper `
  --compute-device cpu --compute-type int8 --language ko
```

로봇을 연결할 때 터미널 1만 아래 파일로 교체한다. 두 프로세스는 동일한
`control_mode.json`을 사용한다.

```bash
# macOS
python balloon_intercept.py --hub-name "Team5" --control-mode-file control_mode.json
```

```powershell
# Windows
python balloon_intercept_win.py --hub-name "Team5" --control-mode-file control_mode.json
```

## 4. 속도 조정

- `base`가 정확도와 속도의 기본 균형이다.
- 더 빠른 반응이 필요하면 macOS는 `--model mlx-community/whisper-tiny`,
  Windows는 `--model tiny`를 사용한다.
- `--silence-ms 300`은 발화 종료 대기를 줄이지만, 문장 중간의 짧은 침묵에서 잘릴 수 있다.
- `--no-wake-word`는 호출어를 따로 말하는 한 단계를 없앤다.
- 음성 추론은 카메라와 별도 프로세스이므로 카메라 FPS를 직접 대기시키지 않는다.
- 처음 한 번의 모델 다운로드 시간은 실제 명령 처리 지연과 구분해야 한다.

## 5. 자동 테스트

macOS와 Windows 백엔드 선택, VAD, 호출어 상태, 명령 분류는 하드웨어 없이 테스트할 수 있다.

```bash
cd "/path/to/Final_project"
python -m unittest discover -s tests -v
```

Windows 실기 검증은 마이크 장치, PortAudio 드라이버, CPU/GPU 런타임 차이 때문에 별도
Windows PC에서 최종 확인해야 한다.
