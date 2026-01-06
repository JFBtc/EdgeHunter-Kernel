# V1a Checklist — Core Kernel (Silent Observer)

Référence: `Core_Kernel_V1a_Spec_FINAL.md`  
Objectif V1a: boucle live stable + ingestion L1 + publication Snapshot atomique + Hard Gates + TriggerCards append-only.  
Interdiction V1a: exécution, stratégie, T&S, historique, multi-instrument.

---

## 1) Scope / Non-goals (doit rester vrai)
- [ ] Aucun ordre: pas de placement, pas d’OCO/brackets, pas de suivi position, pas de reconciliation.
- [ ] Pas de Time & Sales (ni classification aggressor).
- [ ] Pas de stratégie / pas de signaux (sauf “Would Trade Allowed=YES/NO” via Hard Gates).
- [ ] Pas d’historique/seeding (ATR/VWAP/levels), pas de backtest/replay, pas de ML.
- [ ] Un seul instrument par run: MNQ **ou** MES (jamais les deux).
- [ ] Pas de front-month resolver: `contract_key` à échéance explicite.

## 2) Architecture (invariants “single-writer”)
- [ ] IBKR adapter ne modifie jamais l’état partagé; il pousse des événements normalisés dans une InboundQueue.
- [ ] Engine loop = seul writer: draine la queue, met à jour l’état interne, publie un SnapshotDTO atomique (copy-on-write).
- [ ] UI = read-only sur SnapshotDTO; UI n’appelle jamais IBKR.
- [ ] UI → CommandQueue bornée; commandes appliquées uniquement au boundary de cycle (coalescing last-write-wins pour Intent/ARM).

## 3) IBKR Adapter (minimum requis)
- [ ] Connect/disconnect avec backoff exponentiel + storm control.
- [ ] Qualify contrat (un seul instrument) : `contract_key -> conId`.
- [ ] Abonnement L1: bid/ask/last (+ sizes si dispo).
- [ ] `md_mode` exposé: REALTIME | DELAYED | FROZEN | NONE.
- [ ] Subscription manager idempotent: re-apply on reconnect; jamais resubscribe dans la hot loop.
- [ ] Fail-fast sur collision `clientId` (erreur IBKR 326): log + exit non-zéro.

## 4) Temps & liveness
- [ ] Timezone canonique: America/Toronto.
- [ ] Staleness calculée en monotonic time (pas wall-clock).
- [ ] Maintenir:
  - [ ] `last_any_event_mono_ns`
  - [ ] `last_quote_event_mono_ns`
- [ ] Heartbeat/liveness basé sur quote liveness (pas “any-event”).

## 5) Engine loop (déterministe)
- [ ] À chaque cycle: drain inbound queue (drain complet ou drain borné anti-starvation).
- [ ] Appliquer CommandQueue uniquement au boundary de cycle.
- [ ] Publier 1 SnapshotDTO atomique par cycle (`snapshot_id` monotonic).
- [ ] Timing: `sleep_ms = max(0, target_ms - compute_ms)`.
- [ ] Détection overrun/stall -> `ENGINE_DEGRADED`.

## 6) SnapshotDTO (contrat immuable)
- [ ] `schema_version = "snapshot.v1"` + `app_version`, `config_hash`, `run_id`.
- [ ] Instrument: `symbol`, `contract_key`, `con_id` (nullable), `tick_size`.
- [ ] Quote (nullable): bid/ask/last + sizes + timestamps + `staleness_ms` + `spread_ticks`.
- [ ] Feed: `connected`, `md_mode`, `degraded`, `status_reason_codes`.
- [ ] Session: `in_operating_window`, `is_break_window`, `session_date_iso`.
- [ ] Controls: `intent`, `arm`, `last_cmd_id`, `last_cmd_ts_unix_ms`.
- [ ] Loop health: `cycle_ms`, `cycle_overrun`, `engine_degraded`.
- [ ] Gates: `allowed`, `reason_codes[]`, `gate_metrics{}`.
- [ ] Invariant V1a: `ready == allowed` et `ready_reasons == reason_codes`.

## 7) Hard Gates (codes stables, multi-reasons)
- [ ] ARM_OFF
- [ ] INTENT_FLAT
- [ ] OUTSIDE_OPERATING_WINDOW
- [ ] SESSION_BREAK
- [ ] FEED_DISCONNECTED
- [ ] MD_NOT_REALTIME
- [ ] NO_CONTRACT
- [ ] STALE_DATA (quote missing ou staleness>threshold ou quote silence > heartbeat timeout)
- [ ] SPREAD_UNAVAILABLE (bid/ask invalid/absent)
- [ ] SPREAD_WIDE (spread_ticks > MAX_SPREAD_TICKS)
- [ ] ENGINE_DEGRADED
- [ ] Doctrine: `reason_codes[]` liste tous les gates en échec (pas de “winner”).

## 8) Spread en ticks (instrument-safe)
- [ ] `spread_ticks = ceil((ask - bid) / tick_size)` (conservateur).
- [ ] Toute anomalie bid/ask -> `SPREAD_UNAVAILABLE`.

## 9) TriggerLogger (append-only)
- [ ] Cadence découpée du loop (default 1 Hz fixe).
- [ ] Chaque TriggerCard référence le dernier Snapshot publié au moment du log.
- [ ] JSONL append-only, crash-tolerant (dernière ligne possiblement tronquée mais ignorable).
- [ ] Rotation filename = date locale + run_id; rotation sur changement de date locale (ou restart).
- [ ] `schema_version = "triggercard.v1"` + champs stables.

## 10) UI + commandes (bornées)
- [ ] UI lit uniquement SnapshotDTO; UI n’appelle jamais IBKR.
- [ ] CommandQueue bornée (ex: 100).
- [ ] Coalescing: dernière valeur Intent/ARM avant boundary.
- [ ] Engine écrit `last_cmd_id` et `last_cmd_ts_unix_ms`.

## 11) Config & self-test (startup)
- [ ] Validation stricte config: `client_id`, `host/port`, `instrument.symbol`, `instrument.contract_key`, `instrument.tick_size`.
- [ ] Disk write test pour log dir (fatal si échec).
- [ ] Qualification contrat au démarrage; si échec -> observer avec gate `NO_CONTRACT` (non fatal par défaut).

## 12) Done criteria (acceptance)
- [ ] Run ≥ 4h en operating window sans crash; shutdown propre.
- [ ] Snapshot atomique; `snapshot_id` monotonic; UI jamais “partial”.
- [ ] `arm=false` -> `allowed=false` avec `ARM_OFF`.
- [ ] `md_mode != REALTIME` -> `MD_NOT_REALTIME` en ≤ 1 intervalle de log.
- [ ] quote missing/stale -> `STALE_DATA`.
- [ ] bid/ask invalid -> `SPREAD_UNAVAILABLE`.
- [ ] spread > threshold -> `SPREAD_WIDE`.
- [ ] outside window -> `OUTSIDE_OPERATING_WINDOW`.
- [ ] JSONL parseable après kill (sauf dernière ligne possiblement tronquée).

## 13) Red flags (régression immédiate)
- [ ] Ajout d’exécution (ordres, OCO, brackets) “juste pour tester”.
- [ ] Adapter qui modifie SnapshotDTO ou état partagé (hors InboundQueue).
- [ ] Resubscribe L1 dans la hot loop.
- [ ] Staleness basée sur wall-clock uniquement.
- [ ] `ready` ≠ `allowed`.
- [ ] Multi-instrument ou front-month resolver en V1a.
