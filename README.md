# Tetris da terminale

Gioco Tetris standalone per terminali Linux, scritto in Python usando solo la
biblioteca standard `curses`.

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
