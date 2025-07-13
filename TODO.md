# TODO

## filegit clean
```bash
# 특정 날짜 이전의 모든 버전을 삭제합니다.
filegit clean ~/.zshrc --before 2024-07-12 

# 특정 날짜 이전의 모든 자동 커밋 버전을 삭제합니다. 수동 커밋은 유지됩니다.
filegit clean ~/.zshrc --before 2024-07-12 --keep-manual 

# 가장 최근 20개의 기록은 남기고, 그보다 오래된 기록을 모두 삭제합니다.
filegit clean ~/.zshrc --keep-last 20

# 특정 날짜 이후의 모든 버전을 삭제합니다.
filegit clean ~/.zshrc --auto-only
```

## filegit config
```bash
# 현재 설정(config.json)을 보여줍니다.
filegit config --list

# 자동 정리 기능을 활성화합니다.
filegit config --set auto_cleanup.enabled true

# 자동 정리 기능의 규칙을 설정합니다.
filegit config --set auto_cleanup.rules ...
```