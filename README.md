# Bordado simple

Diseñador de bordados para bordadora industrial (formato Tajima .dst).
Pensado para hacerlo fácil: dibujas la forma, eliges cómo se borda y guardas el .dst.

## Cómo sacar el programa (sin instalar nada)

1. Sube todos estos archivos a un repositorio nuevo en GitHub.
2. Ve a la pestaña **Actions** y espera que termine **Compilar BordadoApp.exe** (unos minutos).
3. Entra a esa ejecución y descarga el archivo **BordadoApp-Windows** (es un .zip con el `BordadoApp.exe` adentro).
4. Abre `BordadoApp.exe` en el computador.

## Cómo usarlo

1. **Dibuja:** haz clic en cada punto de la forma. Doble clic (o Enter) para cerrarla.
2. **Ajusta:** elige la forma y gírala, agrándala o achícala. Puedes arrastrarla con "Mover / elegir".
3. **Cómo se borda:**
   - *Relleno*: llena la forma con líneas. Cambia la dirección de las puntadas con el slider.
   - *Contorno*: solo recorre el borde de la forma.
   - Elige el color con los cuadraditos.
4. **Guarda:** botón verde "Guardar bordado (.dst)". Pasa el archivo a la bordadora por USB.

El diseño se centra solo en el bastidor al guardar.
Atajos: Ctrl+Z deshacer, Ctrl+S guardar, Supr borrar la forma elegida.

## Qué todavía no tiene

- Puntadas de satén (para letras y líneas gruesas).
- Abrir .dst que ya existen.
- Convertir una imagen en bordado.

## Para desarrolladores

    pip install -r requirements.txt
    python main.py
    python -m unittest test_engine -v
