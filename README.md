# Visitas de la Web de Preventores, sin depender de la Mac

Este repositorio entra solo a la Web de Preventores dos veces por día hábil,
lee las visitas asignadas y no asignadas, y manda los datos por e-mail a tu Gmail.
La tarea programada de Claude lee ese e-mail, actualiza el tablero
"Visitas prioritarias 2026" y te manda los avisos de vencimiento y de visitas sin asignar.

Horario: lunes a viernes a las 9:30 y a las 13:30 (hora de Buenos Aires).

Tu usuario y contraseña se guardan cifrados como secretos de GitHub: no están
escritos en ningún archivo y nadie puede verlos, ni siquiera desde el repositorio.

---

## Puesta en marcha (una sola vez, unos 15 minutos)

### 1. Crear el repositorio

1. Entrá a https://github.com/new (si no tenés cuenta, creala; es gratis).
2. Nombre: `visitas-preventores`. Marcá **Private**. Clic en **Create repository**.

### 2. Subir los archivos

1. En el repositorio nuevo, clic en **uploading an existing file**.
2. Arrastrá `actualizar_visitas.py`, `requirements.txt` y `README.md`. Clic en **Commit changes**.
3. El archivo de horarios va en una carpeta oculta, así que se crea a mano:
   **Add file → Create new file**, escribí como nombre exactamente
   `.github/workflows/visitas.yml`, pegá el contenido del archivo `visitas.yml`
   y clic en **Commit changes**.

### 3. Crear una contraseña de aplicación de Gmail

GitHub necesita permiso para mandar el e-mail desde tu Gmail. No se usa tu contraseña
normal de Google, sino una "contraseña de aplicación" que solo sirve para esto.

1. Entrá a https://myaccount.google.com/security con la cuenta **doteiza@gmail.com**.
2. Tenés que tener activada la **Verificación en 2 pasos** (si no la tenés, activala primero).
3. Entrá a https://myaccount.google.com/apppasswords, poné de nombre `GitHub visitas` y clic en **Crear**.
4. Copiá la clave de 16 letras que aparece. Se muestra una sola vez.

### 4. Cargar los secretos

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
Creá estos cuatro, uno por uno (el nombre exacto, en mayúsculas):

| Nombre | Valor |
| --- | --- |
| `PREV_USUARIO` | tu usuario de la Web de Preventores |
| `PREV_CLAVE` | tu contraseña de la Web de Preventores |
| `GMAIL_USUARIO` | `doteiza@gmail.com` |
| `GMAIL_CLAVE_APP` | la clave de 16 letras del paso 3 |

### 5. Probar

1. Pestaña **Actions** → si pide habilitar los workflows, aceptá.
2. Clic en **Datos de visitas (Web de Preventores)** → **Run workflow**.
3. Primero marcá **Solo probar** y clic en **Run workflow**. Al terminar (1 o 2 minutos),
   abrí la corrida y el paso "Leer la Web de Preventores…": tiene que mostrar
   `Resultado: {'asignadas_leidas': …}` y los CSV.
4. Si salió bien, corrélo otra vez **sin** marcar "Solo probar". Te tiene que llegar a
   doteiza@gmail.com un e-mail con asunto `[datos-visitas] DD/MM/AAAA HH:MM`.

Cuando llegue ese e-mail, avisale a Claude para que cambie la tarea programada.

---

## Avisos de vencimiento por Telegram

Además del e-mail, el script manda el aviso de vencimientos a un grupo de Telegram,
gratis y con la API oficial de Telegram. Usa las mismas reglas que el e-mail:

- Corrida de las 9:30: visitas que vencen **hoy**.
- Corrida de las 13:30: visitas que vencen **mañana** (los viernes, de sábado a lunes).
- Si no vence ninguna, no se manda nada.

Las personas que tienen que recibir los avisos solo necesitan tener Telegram y estar en el grupo.

### 1. Crear el bot (una vez, lo hace Daniel)

1. En Telegram, buscá **@BotFather** (tiene la tilde azul de verificado) y abrí el chat.
2. Mandale `/newbot`.
3. Te pide un nombre: por ejemplo `Avisos visitas ART`.
4. Te pide un usuario que termine en `bot`: por ejemplo `avisos_visitas_pampafox_bot`
   (si está tomado, probá otro).
5. Te responde con un **token**, parecido a `123456789:AAH...`. Copialo y no lo compartas:
   quien lo tenga puede mandar mensajes con el bot.

### 2. Crear el grupo

1. En Telegram: **Nuevo grupo**. Agregá a las dos personas y al bot (buscalo por su usuario,
   por ejemplo `avisos_visitas_pampafox_bot`).
2. Ponele un nombre, por ejemplo `Visitas ART`.
3. Dentro del grupo, mandá este mensaje (cambiando por el usuario de tu bot):
   `/start@avisos_visitas_pampafox_bot`

### 3. Averiguar el número del grupo

1. En el navegador, abrí esta dirección reemplazando `TOKEN` por el token del paso 1:
   `https://api.telegram.org/botTOKEN/getUpdates`
2. Buscá en el texto `"chat":{"id":` seguido de un número **negativo**, por ejemplo
   `-4512345678` o `-1001234567890`. Ese número, con el signo menos, es el del grupo.
3. Si la página muestra `"result":[]` (vacío), mandá otra vez el `/start@...` en el grupo y
   recargá la página.

### 4. Cargar los secretos en GitHub

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.

| Nombre | Valor |
| --- | --- |
| `TELEGRAM_TOKEN` | el token del paso 1 |
| `TELEGRAM_CHAT` | el número del grupo del paso 3, con el signo menos |

### 5. Probar

**Actions → Datos de visitas → Run workflow** con **Solo probar** marcado: en el registro
aparece el texto del aviso tal como saldría (o que no hay visitas que venzan).
Después, una corrida normal lo manda al grupo.

En las corridas manuales podés desmarcar **Mandar también el aviso por Telegram**
si solo querés actualizar los datos del tablero sin repetir el aviso.

Para sumar o sacar a alguien de los avisos, agregalo o quitalo del grupo: no hace falta tocar GitHub.

---

## Si algo falla

- **GitHub te avisa por e-mail** cada vez que una corrida falla.
- En la corrida fallida, abajo de todo, hay una **captura-error** con la imagen de la página en el momento del error.
- "rechazó el usuario o la contraseña": revisá `PREV_USUARIO` y `PREV_CLAVE`. Si cambiás la contraseña de la web, actualizá ese secreto.
- "Username and Password not accepted" (Gmail): revisá `GMAIL_CLAVE_APP`; si hace falta, creá una contraseña de aplicación nueva.
- "Telegram rechazó el mensaje": el e-mail de datos salió igual. Si dice *chat not found* o *group chat was upgraded*, el número del grupo cambió: repetí el paso 3 y actualizá `TELEGRAM_CHAT`. Si dice *Unauthorized*, revisá `TELEGRAM_TOKEN`. Si dice *bot was kicked*, volvé a agregar el bot al grupo.
- Si la web bloquea las conexiones desde servidores de GitHub (están en EE. UU.), el login va a fallar siempre aunque los datos estén bien. En ese caso hay que pasar a un servidor virtual en Argentina o Brasil.

## Mantenimiento

- GitHub pausa los horarios de los repositorios sin cambios durante 60 días y avisa por e-mail antes. Para reactivarlos, entrá a **Actions** y tocá **Enable workflow**.
- Para cambiar los horarios, editá la línea `cron` de `.github/workflows/visitas.yml` (está en hora UTC: Buenos Aires + 3).
