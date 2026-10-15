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

## Si algo falla

- **GitHub te avisa por e-mail** cada vez que una corrida falla.
- En la corrida fallida, abajo de todo, hay una **captura-error** con la imagen de la página en el momento del error.
- "rechazó el usuario o la contraseña": revisá `PREV_USUARIO` y `PREV_CLAVE`. Si cambiás la contraseña de la web, actualizá ese secreto.
- "Username and Password not accepted" (Gmail): revisá `GMAIL_CLAVE_APP`; si hace falta, creá una contraseña de aplicación nueva.
- Si la web bloquea las conexiones desde servidores de GitHub (están en EE. UU.), el login va a fallar siempre aunque los datos estén bien. En ese caso hay que pasar a un servidor virtual en Argentina o Brasil.

## Mantenimiento

- GitHub pausa los horarios de los repositorios sin cambios durante 60 días y avisa por e-mail antes. Para reactivarlos, entrá a **Actions** y tocá **Enable workflow**.
- Para cambiar los horarios, editá la línea `cron` de `.github/workflows/visitas.yml` (está en hora UTC: Buenos Aires + 3).
