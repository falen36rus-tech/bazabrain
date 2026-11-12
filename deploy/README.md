# Развёртывание на Ubuntu

Сервер получает только проверенную ветку `production`. Ветка `main` обновляет её после ручного запуска **Actions → Выпустить обновление → Run workflow** в GitHub. Редакторские статьи и файлы находятся в PostgreSQL и томе `uploads`; Git их не хранит.

## 1. Подготовить доступ к закрытому репозиторию

На сервере под отдельной учётной записью для сайта создайте SSH-ключ:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/bazabrain_deploy -N '' -C bazabrain-server
cat ~/.ssh/bazabrain_deploy.pub
```

Скопируйте **только открытый ключ** (`.pub`) в `https://github.com/falen36rus-tech/bazabrain/settings/keys` → **Add deploy key**. Оставьте **Allow write access** выключенным. Закрытый ключ с сервера никому не передавайте. [Описание deploy keys в GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

Добавьте в `~/.ssh/config`:

```sshconfig
Host github-bazabrain
    HostName github.com
    User git
    IdentityFile ~/.ssh/bazabrain_deploy
    IdentitiesOnly yes
```

Для первого SSH-подключения проверьте отпечаток ключа сервера по [официальному списку GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Если исходящий порт 22 закрыт, настройте [SSH через порт 443](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port).

## 2. Запустить сайт после первого выпуска

Нужны Git, Docker Engine с Compose, `curl` и `flock`. Учётной записи для сайта нужен доступ к Docker. Выполните первый ручной выпуск в GitHub, чтобы появилась ветка `production`, затем:

```bash
git clone --branch production --single-branch \
  git@github-bazabrain:falen36rus-tech/bazabrain.git ~/bazabrain
cd ~/bazabrain
cp .env.example .env
chmod 600 .env
```

В `.env` замените образцовые значения `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, домен и HTTPS-адрес. В `DJANGO_ALLOWED_HOSTS` сохраните `127.0.0.1` рядом с доменом для локальной проверки. Организуйте reverse proxy с HTTPS перед портом `127.0.0.1:8000`; не публикуйте том `uploads` и путь `/private/` напрямую. Запуск:

```bash
bash deploy/update.sh
docker compose exec web python manage.py createsuperuser
```

Первый запуск создаёт БД, применяет миграции и записывает исходные версии статей. Выдавайте каждому редактору собственную учётную запись с «Статусом персонала» и группой «Редакторы».

## 3. Включить получение выпущенных обновлений

Под той же учётной записью откройте `crontab -e` и добавьте строку, заменив `/home/kbdeploy` на фактический домашний каталог:

```cron
*/5 * * * * /usr/bin/bash /home/kbdeploy/bazabrain/deploy/update.sh >> /home/kbdeploy/bazabrain-update.log 2>&1
```

Скрипт ничего не меняет, пока ветка `production` не сдвинулась. Перед сменой работающей версии он сохраняет SQL-копию и архив вложений в соседнем каталоге `~/bazabrain-backups`; при ошибке обновление будет повторено при следующем запуске. Держите эти копии отдельно от сервера и задайте срок хранения по правилам компании. Для проверки состояния используйте `docker compose ps`, `docker compose logs web` и журнал `~/bazabrain-update.log`.
