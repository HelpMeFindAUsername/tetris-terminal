# Tetris da terminale — Lobby Edition

Tetris per Linux (incluso Debian/Arch) e macOS, scritto in Python 3.8+ con
la sola libreria standard. Il client usa `curses`; il server funziona anche
senza terminale. **Scarica l'intera repo**: `tetris.py` usa i moduli accanto a lui.

## Avvio veloce

```bash
python3 tetris.py
# Oppure avvia direttamente una partita locale:
python3 tetris.py --singleplayer
```

Il menu offre **SINGLEPLAYER**, **MULTIPLAYER**, **HOST LAN**, **IMPOSTAZIONI**
ed **ESCI**. Servono almeno **47 colonne × 29 righe** con il campo da 10 colonne.
Da **72 colonne** sono visibili anche il campo e il punteggio di un avversario.
Su terminali piu stretti il gioco conserva il tuo campo; dopo l'eliminazione
mostra quello del giocatore che stai osservando. `Tab` cambia avversario.
Ridimensionare il terminale non interrompe il gioco.

## Migliorie al gioco

- Blocchi colorati, temi neon/classico/monocromatico e tre stili di blocco.
- Scia della caduta, lampi sulle righe, particelle, messaggi combo/Tetris e
  bordo rosso quando la pila si avvicina alla cima. Le animazioni non bloccano
  input, gravita o rete.
- Sequenza **7-bag**: ogni gruppo contiene tutti i sette pezzi.
- Pezzo fantasma, riserva utilizzabile una volta per pezzo, fino a cinque
  anteprime e rotazione in entrambe le direzioni con correzione vicino ai bordi.
- Tempo di incastro, velocita e livello iniziale configurabili.
- Bonus combo e Tetris consecutivi; caduta manuale +1 per cella e immediata +2.
- Impostazioni persistenti: nickname, server, porta, TLS/certificato, campo da
  6 a 30 colonne, lobby da 2 a 8 giocatori, handicap da 0 a 10 righe, temi,
  anteprime, effetti, particelle, ghost e suoni del terminale.

Le preferenze sono salvate in `$XDG_CONFIG_HOME/terminal-tetris/settings.json`
o `~/.config/terminal-tetris/settings.json`. Per usare un file diverso:

```bash
python3 tetris.py --settings-file ./preferenze.json
python3 tetris.py --width 14 --nickname Mario
```

Le password delle lobby non vengono salvate nelle preferenze.

In **IMPOSTAZIONI → Stile dei blocchi**, usa **Sinistra/Destra** o **Invio**
per scegliere **Quadrati pieni `██`** oppure **Parentesi quadre `[]`**, come
nella versione originale. E disponibile anche lo stile **Contorni `<>`**.
La scelta si salva uscendo dalle impostazioni con **Esc** e si applica a
pezzi, anteprime, campi degli avversari e righe iniziali del vincitore.

## Controlli

| Tasto | Azione |
| --- | --- |
| Frecce sinistra/destra oppure `A`/`D` | Movimento |
| Freccia giu oppure `S` | Caduta manuale |
| Freccia su, `W` oppure `X` | Rotazione oraria |
| `Z` | Rotazione antioraria |
| `Spazio` | Caduta immediata |
| `C` | Riserva/scambio del pezzo |
| `P` | Pausa in singleplayer |
| `Tab` | Cambia avversario o giocatore osservato |
| `R` | Nuova partita dopo il game over locale; pronto in lobby/classifica |
| `Invio` | Il creatore avvia il round quando tutti sono pronti |
| `Q` oppure `Esc` | Torna alla schermata precedente/esci dalla lobby |

## Lobby e round multiplayer

1. Collegati allo stesso server, usando un nickname diverso per ogni giocatore.
2. Nella schermata lobby premi **C**, inserisci nome e password. Le regole e
   il numero di posti vengono presi dalle tue impostazioni.
3. Gli altri premono **F** per cercare il nome, selezionano la lobby con
   **Invio** e inseriscono la password. La ricerca ignora maiuscole/minuscole;
   la password le distingue.
4. Tutti premono **R** per essere pronti. Il creatore preme **Invio**:
   dopo tre secondi il round inizia con la stessa sequenza di pezzi per tutti.
5. **Chi perde rimane eliminato e puo osservare gli altri.** Non puo
   ricominciare da solo. Il round prosegue anche quando resta un solo giocatore.
6. Quando **tutti i partecipanti hanno perso**, compare la classifica.
   Vince chi ha piu punti, indipendentemente dall'ordine di eliminazione.
   In caso di pari punteggio la vittoria e condivisa.
7. La classifica rimane visibile finche i giocatori non sono nuovamente pronti
   e il creatore avvia un altro round. **Il vincitore precedente parte con
   cinque righe incomplete sul fondo** (valore configurabile dal creatore).
   Ogni riga ha un buco nello stesso canale: sono cancellabili con i pezzi
   normali. Il pannello mostra quante ne restano e il tempo impiegato a ripulirle.
   L'handicap non si accumula: riguarda solo i vincitori del round precedente.

Chi entra a round iniziato rimane spettatore fino al successivo. Chi esce o
perde la connessione viene eliminato, mantenendo il punteggio del round.
Se esce il creatore, la gestione passa a un altro membro. Se qualcuno esce
durante il conto alla rovescia, la partenza viene annullata e si torna alla lobby.

Il server calcola movimento, gravita, punteggio, eliminazioni e classifica;
i client inviano solo comandi. In multiplayer non esiste pausa individuale.
La larghezza e le altre regole della lobby vengono applicate automaticamente
a tutti: non occorre configurarle allo stesso modo sui client.

## Server Debian con IP pubblico

Copia questa repo sulla macchina Debian con Python/systemd, quindi esegui
dalla sua directory (sostituisci l'IP di esempio con quello del server):

```bash
sudo bash scripts/install-server-debian.sh --public-ip 203.0.113.10 --port 45454
```

L'installer installa Python/OpenSSL, copia il server in `/opt/terminal-tetris`,
crea un utente di servizio senza login e abilita `terminal-tetris.service`.
Il servizio parte al boot e riparte dopo un errore. Il server ascolta su
`0.0.0.0`; **TLS e abilitato per impostazione predefinita** con un certificato
autofirmato per l'IP, valido un anno. Ripetere l'installer aggiorna il codice
e conserva il certificato esistente ancora valido per quell'IP.

Consenti la **porta TCP 45454** sia nel firewall della macchina sia nelle
regole del provider. Se usi UFW e lo hai gia attivato, puoi aggiungere
`--open-firewall` all'installer. Lo script non attiva UFW automaticamente.
Se la macchina e dietro un router/NAT, inoltra la stessa porta verso di lei.

Distribuisci ai giocatori il **solo certificato pubblico**
`/opt/terminal-tetris/server.crt`, per esempio scaricandolo via SSH:

```bash
scp utente@203.0.113.10:/opt/terminal-tetris/server.crt ./server.crt
python3 tetris.py --server 203.0.113.10 --port 45454 --ca-file ./server.crt --nickname Mario
```

`--ca-file` abilita TLS e verifica certificato e indirizzo del server. Ogni
giocatore deve avere tutta la repo del client e il certificato pubblico.
La chiave privata resta sul server in `/etc/terminal-tetris/server.key`.

Per un certificato esistente, per esempio per un dominio:

```bash
sudo bash scripts/install-server-debian.sh --port 45454 \
  --tls-cert /percorso/fullchain.pem --tls-key /percorso/privkey.pem
python3 tetris.py --server tetris.example.com --port 45454 --tls --nickname Mario
```

I certificati vengono copiati: dopo il rinnovo riesegui l'installer con i
percorsi aggiornati. Per il certificato autofirmato, fornisci una nuova coppia
tramite `--tls-cert`/`--tls-key` quando scade e distribuisci il nuovo certificato.

Gestione del servizio:

```bash
sudo systemctl status terminal-tetris
sudo journalctl -u terminal-tetris -f
sudo systemctl restart terminal-tetris
sudo systemctl stop terminal-tetris
```

Le lobby e le vittorie sono in memoria: riavviare il servizio le cancella.
Le password sono conservate solo come hash PBKDF2 con salt, non vengono
trasmesse negli elenchi o nello stato delle partite, e i tentativi errati
sono limitati per indirizzo IP. Input e code di rete hanno limiti di dimensione.
Il server supporta, per impostazione predefinita, 32 lobby e 128 connessioni.

## LAN e avvio manuale del server

Dal menu **HOST LAN** o con `--host` avvii un server locale e apri il browser
delle lobby. Premi **C** per crearne una e condividi IP LAN, nome e password.
Gli altri si collegano tramite **MULTIPLAYER** oppure `--join`:

```bash
python3 tetris.py --host --port 45454 --nickname Mario
python3 tetris.py --join 192.168.1.42 --port 45454 --no-tls --nickname Luigi
```

Il server integrato rimane acceso finche l'host resta nelle schermate online.
Per tenere acceso un server indipendente senza interfaccia:

```bash
python3 tetris_server.py --bind 0.0.0.0 --port 45454
# Con TLS:
python3 tetris_server.py --port 45454 --cert server.crt --key server.key
```

TCP senza TLS e previsto per la LAN. L'installer offre `--plain-tcp` per
questo caso. Il vecchio collegamento diretto 1v1 e sostituito dalle lobby;
`--host` e `--join` sono mantenuti con il nuovo flusso.

Per tutte le opzioni:

```bash
python3 tetris.py --help
python3 tetris_server.py --help
bash scripts/install-server-debian.sh --help
```

## Verifica e struttura

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/install-server-debian.sh
```

I test coprono regole, hold, combo, righe iniziali, attesa di tutti i giocatori,
classifica, round successivi, spettatori, disconnessioni, lobby indipendenti,
password, impostazioni, frammentazione TCP e certificati TLS. Per i test TLS
serve il comando `openssl`; non servono pacchetti Python aggiuntivi.

| File | Responsabilita |
| --- | --- |
| `tetris.py` | Avvio e opzioni CLI |
| `tetris_game.py` | Regole deterministiche e snapshot |
| `tetris_ui.py` | Schermate curses ed effetti |
| `tetris_settings.py` | Preferenze JSON validate e salvataggio atomico |
| `tetris_network.py` | Client TCP/TLS con buffer per letture/scritture parziali |
| `tetris_server.py` | Server, lobby e round autoritativi |
| `scripts/install-server-debian.sh` | Installazione Debian/systemd |

Il protocollo e JSON su TCP, un oggetto per riga, versione 1. Le richieste
principali sono `hello`, `list`, `create`, `join`, `ready`, `start`, `action`,
`leave` e `ping`; `request_id` collega ogni risposta alla richiesta. Le azioni
includono il numero del `round` per scartare comandi ritardati di round precedenti.
Il server pubblica lo stato delle lobby dieci volte al secondo.
Per i comandi del giocatore invia subito un aggiornamento del suo campo,
senza aspettare lo snapshot periodico.

Riferimenti per la configurazione: [TLS in Python](https://docs.python.org/3/library/ssl.html)
e [servizi systemd su Debian](https://manpages.debian.org/bookworm/systemd/systemd.exec.5.en.html).
