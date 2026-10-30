# Bordado simple

Diseñador de bordados para bordadora industrial (formato Tajima .dst).
Pensado para hacerlo fácil: pones el tamaño del bastidor, dibujas o importas la forma, eliges cómo se borda y guardas el .dst.

## Cómo sacar el programa (sin instalar nada)

1. Sube todos estos archivos a un repositorio en GitHub.
2. Ve a la pestaña **Actions** y espera que termine **Compilar BordadoApp.exe** (unos minutos).
3. Entra a esa ejecución y descarga el archivo **BordadoApp-Windows** (es un .zip con el `BordadoApp.exe` adentro).
4. Abre `BordadoApp.exe` en el computador.

## Cómo usarlo

1. **Bastidor:** arriba del panel pon el ancho y alto del bastidor que vas a usar (en mm). El máximo es 380 × 260.
2. **Dibuja:** haz clic en cada punto de la forma. Doble clic (o Enter) para cerrarla.
3. **Importa** (opcional): botón "Foto o vector → bordado".
   - `.svg`: cada figura se borda con su color. Las letras con agujeros quedan bien.
   - `.png` / `.jpg`: la foto se separa en colores. Es una aproximación: revisa el resultado y borra lo que sobre (por ejemplo, el fondo).
   - `.ai` o `.pdf`: ábrelos en Inkscape y guárdalos como SVG.
4. **Calcar:** "Cargar foto de fondo" pone una foto debajo del bastidor. Arrástrala y ajusta su transparencia y ancho.
5. **Ajusta:** elige una forma y gírala, agrándala o achícala. Puedes arrastrarla con "Mover / elegir".
6. **Cómo se borda:**
   - *Relleno*: llena la forma. La dirección de las puntadas se cambia con el slider.
   - *Contorno*: solo recorre el borde.
   - *Satén*: bordado de ancho fijo, para letras y líneas gruesas. Dibuja una línea con "Dibujar línea de satén" y elige su ancho en mm (3 a 5 mm es lo normal). Si importas un SVG, las líneas abiertas con borde grueso también quedan en satén.
   - Elige el color con los cuadraditos.
7. **Guarda:** botón verde "Guardar bordado (.dst)". Pasa el archivo a la bordadora por USB.

Las reglas arriba y a los lados muestran el tamaño. El diseño se centra solo en el bastidor al guardar.
Atajos: Ctrl+Z deshacer, Ctrl+S guardar, Supr borrar la forma elegida.

## Qué todavía no tiene

- Abrir .dst que ya existen.
- Satén con esquinas muy cerradas: en ángulos agudos las columnas se cruzan. Conviene dividir la línea en tramos.

## Para desarrolladores

    pip install -r requirements.txt
    python main.py
    python -m unittest test_engine -v
