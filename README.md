# Tetris da terminale

Tetris standalone giocabile direttamente nel terminale, compatibile con:

- Arch Linux e altre distribuzioni Linux
- macOS tramite Terminale o iTerm2

Il gioco è scritto in Python e usa solo la libreria standard `curses`: non
servono dipendenze Python esterne.

## Funzionalità

- Tutti i sette pezzi classici: `I`, `O`, `T`, `S`, `Z`, `J`, `L`
- Movimento, rotazione e caduta rapida
- Ghost piece: mostra il punto in cui atterrerà il pezzo
- Animazione lampeggiante quando una o più righe vengono distrutte
- Punteggio, livello e conteggio delle righe completate
- Anteprima del pezzo successivo
- Campo di gioco personalizzabile da 6 a 30 colonne
- Pausa, game over e riavvio
- Colori automatici quando il terminale li supporta

## Requisiti

- Python 3.8 o superiore
- Un terminale di almeno 34 righe e 52 colonne con la larghezza predefinita
- Supporto `curses`, incluso nella distribuzione standard di Python su Linux
  e macOS

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

## Utilizzo

La larghezza predefinita del campo è di 10 colonne. Puoi personalizzarla
all'avvio:

```bash
./tetris.py --width 14
```

Sono supportate larghezze da 6 a 30 colonne. Per visualizzare tutte le opzioni:

```bash
./tetris.py --help
```

Se il terminale è troppo piccolo, il gioco mostra la dimensione minima
necessaria: ridimensiona la finestra e riprova.

## Controlli

| Tasto | Azione |
| --- | --- |
| Freccia sinistra/destra | Muovi il pezzo |
| Freccia su | Ruota il pezzo |
| Freccia giù | Discesa manuale |
| `Spazio` | Caduta immediata |
| `P` | Metti in pausa o riprendi |
| `Q` | Esci |
| `R` | Ricomincia dopo il game over |

## Avvio da macOS

Se il file non è eseguibile, abilita l'esecuzione una sola volta:

```bash
chmod +x tetris.py
```

In alternativa puoi sempre avviarlo con:

```bash
python3 tetris.py
```
