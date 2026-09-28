# Tetris da terminale

Gioco Tetris standalone per terminali Linux e macOS, scritto in Python usando
solo la biblioteca standard `curses`.

## Installazione

Su macOS, installa Python 3 se non è già presente:

```bash
brew install python
```

Su Arch Linux:

```bash
sudo pacman -S python
```

Poi avvia il gioco dal Terminale macOS, iTerm2 o da un terminale Linux:

```bash
chmod +x tetris.py
./tetris.py
```

Puoi scegliere la larghezza del campo all'avvio:

```bash
./tetris.py --width 14
```

Sono supportate larghezze da 6 a 30 colonne. Il blocco trasparente indica dove
atterrerà il pezzo. Le righe completate lampeggiano prima di essere distrutte.

Comandi: frecce per muovere/ruotare, `Spazio` per la caduta immediata, `P` per
pausare e `Q` per uscire. Dopo il game over, premi `R` per ricominciare.
