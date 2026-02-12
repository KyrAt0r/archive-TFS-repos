# Что делает программа

Программа архивирует все Git-репозитории внутри Team Project в TFS / Azure DevOps Server (on-prem).

Для каждого репозитория выполняется:

1) Получение списка репозиториев через REST API: `/_apis/git/repositories?api-version=...`
2) `git clone --mirror` (полная история + refs)
3) `git bundle create <repo>.bundle --all` (все ветки/теги)
4) `git bundle verify <repo>.bundle` (проверка целостности)
5) Опционально: упаковка в ZIP (1 репозиторий = 1 ZIP), внутри:
   - `<repo>.bundle`
   - `README_RESTORE_EN.txt`
   - `README_RESTORE_EN.txt`

6) Опционально: удаление временного `mirrors/` и/или `.bundle` после ZIP

## Требования

  - Python 3.10+
  - git должен быть установлен и доступен в PATH 
  - Доступ к вашему TFS/Azure DevOps Server и права на чтение репозиториев 
  - REST API репозиториев доступен по пути:
    - `https://<server>/<collection>/<project>/_apis/git/repositories?api-version=6.0`

## Авторизация (выбор в GUI / CLI)

Поддерживаются 2 режима:

A) PAT (рекомендуется)

Самый надёжный способ для Azure DevOps / TFS.

B) Логин/пароль (Basic)

Работает только если сервер разрешает Basic Auth.
Если у вас доменная авторизация/SSO (NTLM/Kerberos) — чаще всего не сработает, используйте PAT.

### Запуск GUI

Из корня проекта:
```python run_gui.py```

#### В GUI:
1) Заполните **Collection URL, Project, Out root** 
2) Выберите Auth mode: PAT или Username/Password 
3) Отметьте опции (ZIP / Delete bundle after ZIP / Skip existing / Keep mirrors)
4) Нажмите **Start** 
5) Для остановки — **Cancel**

### Запуск CLI
#### CLI — PAT
**Windows (cmd/powershell):**
```
python run_cli.py ^
  --collection-url "https://tfs.company.ru/tfs/company" ^
  --project "SampleProject" ^
  --out-root "D:\Archive\SampleProject" ^
  --auth-mode pat ^
  --pat "YOUR_PAT" ^
  --zip-bundles ^
  --skip-existing
```

**Linux/macOS:**

```
python run_cli.py \
  --collection-url "https://tfs.example.local/tfs/DefaultCollection" \
  --project "SampleProject" \
  --out-root "/mnt/archive/SampleProject" \
  --auth-mode pat \
  --pat "YOUR_PAT" \
  --zip-bundles \
  --skip-existing
```
**CLI — логин/пароль (Basic)**
```
python run_cli.py ^
  --collection-url "https://tfs.example.local/tfs/DefaultCollection" ^
  --project "SampleProject" ^
  --out-root "D:\Archive\SampleProject" ^
  --auth-mode userpass ^
  --username "DOMAIN\user" ^
  --password "pass" ^
  --zip-bundles ^
  --skip-existing
```


### Что будет создано в out-root
```
out-root/
  bundles/     (*.bundle или *.zip)
  logs/        (логи выполнения)
  reports/     (CSV отчёт)
  mirrors/     (временные mirror-клоны, если включён keep)
  README_RESTORE.md
```


### Восстановление репозитория из bundle

Если у вас есть файл `repo.bundle`:

**Вариант A (простой):**
```bush
git clone repo.bundle repo
cd repo
git checkout master
```

**Вариант B (вручную):**
```bush
mkdir repo
cd repo
git init
git remote add origin ../repo.bundle
git fetch origin --all
git checkout master
```

### Частые проблемы
  - git не найден: установите git и добавьте в PATH 
  - 401/403: неверный PAT или нет прав на репозитории 
  - LFS: git bundle не включает LFS-объекты автоматически (их нужно обрабатывать отдельно)
  - Логин/пароль не работает: сервер может требовать NTLM/SSO — используйте PAT