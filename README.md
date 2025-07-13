# filegit
## 당신의 파일을 위한 자동 타임머신
자동 커밋, 수동 커밋을 지원하는 버전 관리 시스템

### ✨ 주요 특징
* 개별 파일 집중: 폴더가 아닌 파일 단위로 감시합니다.
* 자동 스냅샷: 백그라운드 데몬이 지정된 파일의 모든 저장(save) 이벤트를 감지하여 자동으로 버전을 기록합니다.
* 직관적인 타임라인: 터미널 기반의 대시보드에서 파일의 모든 역사를 탐색하고, 과거 버전과 현재 내용을 비교하며, 클릭 한 번으로 복원할 수 있습니다.
* 중앙 집중 관리: ~/.filegit 단 하나의 폴더에서 모든 파일의 이력을 관리하므로, 당신의 프로젝트 폴더를 더럽히지 않습니다.
* 가벼움과 단순함: 브랜치 관리 없이 파일 저장에 집중합니다.

## 시작하기
#### 1. 요구사항
* Python 3.8 이상
* macOS 또는 Linux 환경

#### 2. 설치
filegit의 종속 패키지를 설치합니다.
```bash
pip install "textual[dev]" click python-daemon watchdog
``` 

#### 3. 초기화
filegit을 사용하기 위해 시스템에 저장소를 단 한 번 생성합니다.
```bash
filegit init
```

## 사용법
#### 1. 자동 감시
파일을 자동으로 감시하려면, 감시할 파일을 지정합니다.
```bash
# 1. 중요한 파일들을 '감시 목록'에 추가합니다.
filegit watch ~/.zshrc
filegit watch ~/Documents/my_important_notes.md

# 2. 감시 목록을 확인합니다.
filegit watch-list

# 3. 백그라운드에서 자동 감시 데몬을 시작합니다.
filegit daemon-start
```

#### 2. 타임라인 탐색 (대시보드)
파일의 모든 버전을 탐색하고 비교할 수 있는 대시보드를 실행합니다.
```bash
filegit timeline ~/.zshrc
```

#### 3. 데몬 제어
데몬을 시작하거나 중지할 수 있습니다.
```bash
filegit daemon-status	# 데몬의 실행 상태와 최신 로그를 확인합니다.
filegit daemon-stop	# 실행 중인 자동 감시 데몬을 종료합니다.
filegit unwatch <file>	# 특정 파일을 감시 목록에서 제거합니다. (적용을 위해 데몬 재시작 필요)
filegit daemon-start	# 데몬을 다시 시작합니다.
```