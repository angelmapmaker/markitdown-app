# Conversor a Markdown

Página web local que convierte documentos y videos de YouTube a Markdown limpio con
[MarkItDown](https://github.com/microsoft/markitdown), para pasarle a Claude (u otra IA)
texto en vez de PDFs y gastar menos tokens.

## Qué hace

- Convierte **PDF, Word, PowerPoint, Excel, HTML, CSV, EPUB, imágenes, audio** y **videos de YouTube** (transcripción).
- **Repara tildes y símbolos raros** (`canciÃ³n` → `canción`) con `ftfy`.
- **Compacta** el resultado: quita espacios, líneas vacías e imágenes base64.
- **Divide** libros y PDFs grandes:
  - **Por capítulos**: usa los marcadores del PDF, el índice del libro o las líneas «Capítulo N».
  - **En N partes iguales**: corta al final de una frase.
- Con **Ctrl+clic** junta varios capítulos o partes y los descarga en un solo `.md`
  (por ejemplo `libro_cap1_cap5.md`).
- **↻ Volver a convertir** repite la última conversión con la configuración nueva.

Todo corre en tu PC: los archivos no se suben a ningún servidor.

## Instalación

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>.
   En el instalador marca **"Add python.exe to PATH"**.
2. Descarga el proyecto:
   ```bash
   git clone https://github.com/angelmapmaker/markitdown-app.git
   ```
   (o descarga el ZIP desde GitHub: botón **Code → Download ZIP**).
3. Haz doble clic en **`iniciar.bat`**.

La primera vez instala automáticamente `markitdown[all]`, `ftfy` y `pypdf`
(necesita internet y tarda unos minutos). Luego se abre <http://127.0.0.1:8765>.

> Usa siempre la app desde `http://127.0.0.1:8765`. Si abres `index.html` con doble clic,
> la página no puede convertir.

## Uso

| Pestaña | Para qué |
|---|---|
| **Carpeta** | Escribe la ruta de una carpeta, pulsa *Ver archivos* y haz clic en uno, o usa *Convertir todos*. |
| **Archivo** | Arrastra un archivo. Para guardarlo en disco, indica una *Carpeta de salida*. |
| **YouTube** | Pega el enlace; los idiomas de subtítulos van por prioridad (`es,en`). |

Los `.md` se guardan junto al original, o en la carpeta de salida si la indicas.
Al dividir, se crea una carpeta `nombre_capitulos` o `nombre_partes` con un archivo por
sección y un `00_indice.md`.

## Actualizar a la última versión

```bash
git pull
```

## Archivos

- `app.py`: servidor local en Python (conversión, reparación de texto, división en capítulos).
- `index.html`: interfaz web.
- `iniciar.bat`: arranca la app en Windows.

## Limitaciones

- Los PDFs escaneados (que son imágenes) no tienen texto, así que salen vacíos.
- La división por capítulos depende de que el libro tenga marcadores, índice o títulos «Capítulo N».
- Solo se abre en la PC donde corre (escucha en `127.0.0.1`).
