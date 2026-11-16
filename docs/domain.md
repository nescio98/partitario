# Domain requirements

What the app must do once built. The current behaviour to reproduce and improve
is the spreadsheet `PartitaIva2026.xlsx` (gitignored: it holds real financial
data — never commit it or copy its figures into fixtures). Its sheets:
Dashboard, Parametri, Scadenze, Fatture, Conto Titoli, Conto Corrente,
Estratto Conto.

## Principles

- Everything the spreadsheet hard-codes becomes configurable data.
- Money is `Decimal` / `DecimalField` end to end, never float.
- A closed fiscal year is never recomputed with newer rules.

## Tax configuration (`fiscal`)

One parameter set per fiscal year. From the *Parametri* sheet:

- coefficiente di redditività
- aliquota imposta sostitutiva (5% for the first five years, then 15%)
- aliquota INPS and riduzione contributiva
- minimale INPS annuo and contributo maternità (they determine the fixed
  quarterly rata)
- soglia and importo of the bollo
- soglia ricavi of the regime forfettario

A law change in 2027 is a new 2027 configuration; 2026 results must not move.
First profile to configure: artigiani, sviluppo software, 2026.

## Scadenze (`deadlines`)

Configurable per year. The sheet has three families:

- **INPS fissi**: four quarterly rate. The 4ª rata of year N is due in
  February N+1.
- **Bollo**: one per quarter, amount = bollo of the invoices issued in that
  quarter. Q4 is due in February N+1.
- **Imposta sostitutiva and INPS eccedenza minimale**: saldo of year N plus the
  acconti for N+1 (40% and 60%), due in June and November N+1.

A scadenza belongs to the fiscal year it is computed from, not to the year it is
paid in — so in early N+1 the open items of N and the first items of N+1
coexist. In the sheet a scadenza counts as paid when a conto corrente movement
carries its category; the app reconciles against bank movements.

## Fatture (`invoices`)

Data emissione, data incasso, numero, cliente, imponibile, bollo, and the
uploaded document in the private bucket. Derived per invoice from the
configuration of its fiscal year: reddito imponibile, imposta sostitutiva, INPS
variabile, amount to set aside. Bollo applies above the configured threshold.
Status: da incassare / incassata.

## Banks and accounts (`banking`)

A bank/broker is a configurable entity with exactly one conto corrente and one
conto titoli. More can be added over time.

- **Conto corrente**: data, descrizione, categoria, entrata / uscita.
- **Conto titoli**: data, operazione (acquisto / vendita), symbol, quantità,
  prezzo, commissioni; each trade produces a cash flow on the conto corrente
  side.
- **Estratto conto**: derived, never typed — the union of conto corrente
  movements and the cash flows of conto titoli trades, with a running balance,
  filterable by one, several or all banks/brokers.

## Dashboard (`dashboard`)

A refined version of the sheet's Dashboard: fatturato and incassato, share of
the soglia ricavi used and margin left, taxes and contributions to set aside,
totals due / paid / outstanding, next scadenza with days remaining.
