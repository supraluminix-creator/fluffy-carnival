"""
Adapter X (Twitter) — opt-in, minimal, robuste.

Contrat:
- Entrée: watchlist (env X_WATCHLIST: "#BTC,#ETH,@binance"), limite par requête, TTL cache
- Sortie: dict JSON sérialisable { ts, queries, items: [ {id, text, created_at, author, metrics, matched} ], meta }

Caractéristiques:
- Utilise la façade HTTP unifiée (pipeline.http.async_fetch_json)
- Flags/env: X_ENABLED, X_BEARER_TOKEN, X_WATCHLIST, X_LIMIT, X_TIMEOUT, X_CACHE_TTL
- Cache local (fichier) pour limiter les appels si TTL non expiré
- Pas de dépendances externes; désactivé par défaut; tolérant aux erreurs réseau

Notes:
- Endpoints X API v2 (search recent). Nécessite un Bearer Token (X_BEARER_TOKEN).
- Ce module ne lance aucun appel si X_ENABLED != 1 ou token absent.
 - Mode additionnel: retweeters (GET /2/tweets/:id/retweeted_by) — 1 appel max/run.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import AsyncClient
else:  # pragma: no cover - typing fallback
    AsyncClient = Any

try:
    # Façade HTTP unifiée
    from pipeline.http import async_fetch_json
except Exception:  # pragma: no cover - fallback import

    async def async_fetch_json(
        url: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        retries: int | None = None,
        backoff_base: float | None = None,
        client: AsyncClient | None = None,
    ) -> Any:
        raise RuntimeError("pipeline.http.async_fetch_json indisponible")


API_BASE = "https://api.twitter.com/2"


@dataclass
class XConfig:
    enabled: bool
    bearer_token: str | None
    watchlist: list[str]
    limit: int
    timeout: float
    cache_ttl: int  # 15 min par défaut
    disable_search: bool
    use_lang_filter: bool
    exclude_retweets: bool
    pacing_ms: int
    selector: str
    rate_window_app_sec: int
    rate_window_token_sec: int
    mode: str  # feed | retweeters
    retweeters_tweet_id: str | None
    retweeters_limit: int


def _is_enabled() -> bool:
    return os.environ.get("X_ENABLED", "0") in {"1", "true", "yes", "on"}


def _parse_watchlist(raw: str | None) -> list[str]:
    if not raw:
        return []
    items: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        t = part.strip()
        if not t:
            continue
        # normaliser hashtag SOL -> #SOL
        if t.lower() == "solana":
            t = "#SOL"
        if not (t.startswith("#") or t.startswith("@")):
            # heuristique: si alphanum court, on le considère hashtag
            t = f"#{t}"
        items.append(t)
    # dédupliquer en préservant l'ordre
    seen: set[str] = set()
    uniq: list[str] = []
    for it in items:
        if it.lower() in seen:
            continue
        seen.add(it.lower())
        uniq.append(it)
    return uniq


def load_config() -> XConfig:
    return XConfig(
        enabled=_is_enabled(),
        bearer_token=os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN"),
        watchlist=_parse_watchlist(os.environ.get("X_WATCHLIST")),
        limit=int(os.environ.get("X_LIMIT", "50")),
        timeout=float(os.environ.get("X_TIMEOUT", "12")),
        cache_ttl=int(os.environ.get("X_CACHE_TTL", "900")),
        disable_search=os.environ.get("X_DISABLE_SEARCH", "0") in {"1", "true", "yes", "on"},
        use_lang_filter=os.environ.get("X_USE_LANG", "1") in {"1", "true", "yes", "on"},
        exclude_retweets=os.environ.get("X_EXCLUDE_RETWEETS", "1") in {"1", "true", "yes", "on"},
        pacing_ms=int(os.environ.get("X_PACING_MS", "200")),
        selector=os.environ.get("X_SELECTOR", "handles-first"),
        rate_window_app_sec=int(os.environ.get("X_RATE_WINDOW_APP_SEC", os.environ.get("X_RATE_WINDOW_SEC", "900"))),
        rate_window_token_sec=int(
            os.environ.get("X_RATE_WINDOW_USER_SEC", os.environ.get("X_RATE_WINDOW_SEC", "900"))
        ),
        mode=os.environ.get("X_MODE", "feed"),
        retweeters_tweet_id=os.environ.get("X_RETWEETERS_TWEET_ID"),
        retweeters_limit=int(os.environ.get("X_RETWEETERS_LIMIT", "100")),
    )


def _cache_path(watchlist: list[str]) -> Path:
    key = ",".join(watchlist).encode("utf-8")
    h = hashlib.sha1(key).hexdigest()  # nosec - cache key only
    p = Path(".cache") / f"x_curated_{h}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path_token(token: str) -> Path:
    h = hashlib.sha1(token.encode("utf-8")).hexdigest()  # nosec - cache key only
    p = Path(".cache") / f"x_tok_{h}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cache_valid(p: Path, ttl: int) -> bool:
    try:
        if not p.exists():
            return False
        age = time.time() - p.stat().st_mtime
        return age < ttl
    except Exception:
        return False


def _quota_path() -> Path:
    p = Path(".cache") / "x_quota.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _quota_load() -> dict[str, Any]:
    default = {"app": {"next_ts": 0}, "tokens": {}, "selector_state": {"rr": 0}}
    try:
        raw = json.loads(_quota_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return default
    return default


def _quota_save(app_next_ts: int, *, token_next: dict[str, int] | None = None, rr_index: int | None = None) -> None:
    q = _quota_load()
    q["app"] = {"next_ts": int(app_next_ts)}
    if token_next:
        tokmap = q.get("tokens") or {}
        tokmap.update({k: int(v) for k, v in token_next.items()})
        q["tokens"] = tokmap
    if rr_index is not None:
        st = q.get("selector_state") or {}
        st["rr"] = int(rr_index)
        q["selector_state"] = st
    _quota_path().write_text(json.dumps(q), encoding="utf-8")


def _select_token(cfg: XConfig, wl: list[str]) -> tuple[str | None, int | None]:
    if not wl:
        return None, None
    sel = (cfg.selector or "").lower()
    if sel == "handles-first":
        for i, t in enumerate(wl):
            if t.startswith("@"):
                return t, i
        return wl[0], 0
    if sel == "hashtags-first":
        for i, t in enumerate(wl):
            if t.startswith("#"):
                return t, i
        return wl[0], 0
    if sel == "random":
        import random as _r

        i = _r.randrange(0, len(wl))
        return wl[i], i
    # roundrobin (par défaut)
    q = _quota_load()
    rr = int((q.get("selector_state") or {}).get("rr", 0))
    i = rr % len(wl)
    return wl[i], i


def _build_query(token: str, *, use_lang: bool, exclude_rt: bool) -> str:
    # token est #hashtag ou @user
    if token.startswith("#"):
        # Rechercher le hashtag exact; exclure retweets pour réduire bruit
        core = f"{token} -is:retweet" if exclude_rt else token
        if use_lang:
            return f"({core} lang:en) OR ({core} lang:fr)"
        return core
    user = token[1:] if token.startswith("@") else token
    # from:username inclut les tweets de l'auteur; mention capture réponses
    # On évite -is:retweet pour conserver le contexte d'engagement
    base = f"(from:{user} OR @{user})"
    if use_lang:
        return f"({base} lang:en) OR ({base} lang:fr)"
    return base


async def _fetch_one(
    query: str,
    *,
    bearer: str,
    limit: int,
    timeout: float,
) -> dict[str, Any] | None:
    url = (
        f"{API_BASE}/tweets/search/recent"
        f"?query={http_quote(query)}&max_results={min(max(limit, 10), 100)}"
        "&tweet.fields=public_metrics,created_at,lang"
        "&expansions=author_id"
        "&user.fields=username,name,public_metrics"
    )
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        result = await async_fetch_json(url, headers=headers, timeout=timeout)
    except Exception:
        return None
    if isinstance(result, dict):
        return result
    return None


async def _lookup_user(username: str, *, bearer: str, timeout: float) -> dict[str, Any] | None:
    url = f"{API_BASE}/users/by/username/{http_quote(username)}" "?user.fields=username,name,public_metrics"
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        result = await async_fetch_json(url, headers=headers, timeout=timeout)
    except Exception:
        return None
    if isinstance(result, dict):
        return result
    return None


async def _fetch_user_tweets(
    user_id: str,
    *,
    bearer: str,
    limit: int,
    timeout: float,
    exclude_rt: bool,
) -> dict[str, Any] | None:
    max_res = min(max(limit, 10), 100)
    exclude = "&exclude=retweets" if exclude_rt else ""
    url = (
        f"{API_BASE}/users/{http_quote(user_id)}/tweets?max_results={max_res}{exclude}"
        "&tweet.fields=public_metrics,created_at,lang"
    )
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        result = await async_fetch_json(url, headers=headers, timeout=timeout)
    except Exception:
        return None
    if isinstance(result, dict):
        return result
    return None


async def _fetch_retweeters(
    tweet_id: str,
    *,
    bearer: str,
    timeout: float,
) -> dict[str, Any] | None:
    url = f"{API_BASE}/tweets/{http_quote(tweet_id)}/retweeted_by" "?user.fields=username,name,public_metrics"
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        result = await async_fetch_json(url, headers=headers, timeout=timeout)
    except Exception:
        return None
    if isinstance(result, dict):
        return result
    return None


def http_quote(s: str) -> str:
    # éviter d'importer urllib.parse pour rester minimaliste
    from urllib.parse import quote

    return quote(s, safe="")


def _index_users(includes: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not includes:
        return {}
    users = includes.get("users") or []
    return {u.get("id", ""): u for u in users if isinstance(u, dict)}


def _normalize_items(
    payload: dict[str, Any] | None,
    *,
    token: str,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    data = payload.get("data") or []
    if not isinstance(data, list):
        return []
    users = _index_users(payload.get("includes") if isinstance(payload, dict) else None)
    out: list[dict[str, Any]] = []
    for t in data:
        if not isinstance(t, dict):
            continue
        uid = t.get("author_id")
        u = users.get(uid or "", {})
        pm = t.get("public_metrics") or {}
        out.append(
            {
                "id": t.get("id"),
                "text": t.get("text"),
                "created_at": t.get("created_at"),
                "lang": t.get("lang"),
                "author": {
                    "id": uid,
                    "username": u.get("username"),
                    "name": u.get("name"),
                    "followers": (u.get("public_metrics") or {}).get("followers_count"),
                },
                "metrics": {
                    "like": pm.get("like_count"),
                    "retweet": pm.get("retweet_count"),
                    "reply": pm.get("reply_count"),
                    "quote": pm.get("quote_count"),
                },
                "matched": {"token": token, "type": "user" if token.startswith("@") else "hashtag"},
                "source": "x",
            }
        )
    return out


def _normalize_from_timeline(
    payload: dict[str, Any] | None,
    *,
    user: dict[str, Any] | None,
    token: str,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    data = payload.get("data") or []
    if not isinstance(data, list):
        return []
    u = user or {}
    out: list[dict[str, Any]] = []
    for t in data:
        if not isinstance(t, dict):
            continue
        pm = t.get("public_metrics") or {}
        out.append(
            {
                "id": t.get("id"),
                "text": t.get("text"),
                "created_at": t.get("created_at"),
                "lang": t.get("lang"),
                "author": {
                    "id": t.get("author_id"),
                    "username": u.get("username"),
                    "name": u.get("name"),
                    "followers": (u.get("public_metrics") or {}).get("followers_count"),
                },
                "metrics": {
                    "like": pm.get("like_count"),
                    "retweet": pm.get("retweet_count"),
                    "reply": pm.get("reply_count"),
                    "quote": pm.get("quote_count"),
                },
                "matched": {"token": token, "type": "user"},
                "source": "x",
            }
        )
    return out


async def get_curated_feed(
    *,
    watchlist: list[str] | None = None,
    limit: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Récupère un flux X agrégé conforme à la watchlist.

    Ne fait rien si désactivé ou token manquant. Utilise un cache TTL.
    """
    cfg = load_config()
    # Mode retweeters: une requête unique sur /tweets/:id/retweeted_by
    if (cfg.mode or "").lower() == "retweeters":
        tweet_id = (cfg.retweeters_tweet_id or "").strip()
        if not tweet_id:
            return {
                "ts": int(time.time()),
                "queries": 0,
                "items": [],
                "meta": {"reason": "missing_tweet_id", "mode": "retweeters"},
            }
        token_id = f"tweet:{tweet_id}"
        # Charger cache token
        rt_cached_items: list[dict[str, Any]] = []
        rt_seen_ids: set[str] = set()
        tp = _cache_path_token(token_id)
        try:
            if tp.exists():
                tok_data = json.loads(tp.read_text(encoding="utf-8"))
                for it in tok_data.get("items") or []:
                    uid = str((it or {}).get("id"))
                    if uid and uid not in rt_seen_ids:
                        rt_seen_ids.add(uid)
                        rt_cached_items.append(it)
        except Exception:
            pass

        # Quotas
        quotas = _quota_load()
        now = int(time.time())
        app_allowed = now >= int((quotas.get("app") or {}).get("next_ts", 0))
        rt_token_next_map: dict[str, int] = {k: int(v) for k, v in (quotas.get("tokens") or {}).items()}
        token_allowed = now >= int(rt_token_next_map.get(token_id, 0))

        rt_new_items: list[dict[str, Any]] = []
        if app_allowed and token_allowed:
            payload = await _fetch_retweeters(tweet_id, bearer=cfg.bearer_token or "", timeout=cfg.timeout)
            users = (payload or {}).get("data") if isinstance(payload, dict) else None
            if isinstance(users, list):
                for u in users:
                    if not isinstance(u, dict):
                        continue
                    uid = str(u.get("id"))
                    if uid and uid in rt_seen_ids:
                        continue
                    if uid:
                        rt_seen_ids.add(uid)
                    rt_new_items.append(
                        {
                            "id": uid,
                            "user": {
                                "username": u.get("username"),
                                "name": u.get("name"),
                                "followers": (u.get("public_metrics") or {}).get("followers_count"),
                            },
                            "tweet_id": tweet_id,
                            "matched": {"token": token_id, "type": "retweeter"},
                            "source": "x",
                        }
                    )
            # Mise à jour cache token
            from contextlib import suppress

            with suppress(Exception):
                tp.write_text(
                    json.dumps({"ts": now, "token": token_id, "items": rt_new_items}, ensure_ascii=False),
                    encoding="utf-8",
                )
            # Mettre à jour quotas
            next_app = now + max(60, cfg.rate_window_app_sec)
            next_tok = now + max(60, cfg.rate_window_token_sec)
            rt_token_next_map[token_id] = next_tok
            _quota_save(next_app, token_next=rt_token_next_map)

        # Fusion caches + nouveaux
        items = list(rt_cached_items)
        existing_ids = {str(x.get("id")) for x in items if isinstance(x, dict)}
        for it in rt_new_items:
            uid = str(it.get("id"))
            if uid and uid not in existing_ids:
                items.append(it)
                existing_ids.add(uid)

        return {
            "ts": int(time.time()),
            "queries": 1 if rt_new_items else 0,
            "items": items,
            "meta": {
                "mode": "retweeters",
                "watchlist": [token_id],
                "limit": cfg.retweeters_limit,
                "cached": False,
                "source": "x",
                "rate_window_app_sec": cfg.rate_window_app_sec,
                "rate_window_token_sec": cfg.rate_window_token_sec,
                "selected_token": token_id,
                "quota_app_next_ts": int((_quota_load().get("app") or {}).get("next_ts", 0)),
            },
        }
    wl = watchlist if watchlist is not None else cfg.watchlist
    if not wl:
        return {"ts": int(time.time()), "queries": 0, "items": [], "meta": {"reason": "empty_watchlist"}}
    if not cfg.enabled:
        return {"ts": int(time.time()), "queries": 0, "items": [], "meta": {"reason": "disabled"}}
    if not cfg.bearer_token:
        return {"ts": int(time.time()), "queries": 0, "items": [], "meta": {"reason": "missing_token"}}

    cap = limit or cfg.limit
    cache_path = _cache_path(wl)
    if not force_refresh and _cache_valid(cache_path, cfg.cache_ttl):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass

    # Composer depuis caches par token, pour fournir un flux même sans appel réseau
    cached_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for tok in wl:
        tp = _cache_path_token(tok)
        try:
            if tp.exists():
                tok_data = json.loads(tp.read_text(encoding="utf-8"))
                for it in tok_data.get("items") or []:
                    tid = str((it or {}).get("id"))
                    if tid and tid not in seen_ids:
                        seen_ids.add(tid)
                        cached_items.append(it)
        except Exception:
            continue

    # Quotas: 1 requête / fenêtre pour l'app et 1 / fenêtre pour chaque token
    quotas = _quota_load()
    now = int(time.time())
    app_allowed = now >= int((quotas.get("app") or {}).get("next_ts", 0))
    token_next_map: dict[str, int] = {k: int(v) for k, v in (quotas.get("tokens") or {}).items()}

    # Choisir un token à rafraîchir (dont la fenêtre est échue)
    selected_token: str | None = None
    sel_index: int | None = None
    if app_allowed:
        # filtrer ceux autorisés côté token
        candidates = [t for t in wl if now >= int(token_next_map.get(t, 0))]
        if candidates:
            # appliquer la stratégie de sélection sur cette liste
            ordered = candidates
            if (cfg.selector or "").lower() == "handles-first":
                ordered = [t for t in candidates if t.startswith("@")]
                ordered += [t for t in candidates if not t.startswith("@")]
            elif (cfg.selector or "").lower() == "hashtags-first":
                ordered = [t for t in candidates if t.startswith("#")]
                ordered += [t for t in candidates if not t.startswith("#")]
            elif (cfg.selector or "").lower() == "random":
                import random as _r

                _r.shuffle(candidates)
                ordered = candidates
            elif (cfg.selector or "").lower() == "roundrobin":
                rr = int((quotas.get("selector_state") or {}).get("rr", 0))
                if candidates:
                    # simple rr sur candidats
                    ordered = candidates[rr % len(candidates) :] + candidates[: rr % len(candidates)]
            selected_token = ordered[0]
            sel_index = wl.index(selected_token)

    # Réaliser au plus un appel réseau
    search_disabled_dynamic = False
    new_items: list[dict[str, Any]] = []
    if selected_token:
        if selected_token.startswith("@"):
            username = selected_token[1:]
            u = await _lookup_user(username, bearer=cfg.bearer_token or "", timeout=cfg.timeout)
            user_obj = (u or {}).get("data") if isinstance(u, dict) else None
            payload_tl = None
            if user_obj and isinstance(user_obj, dict):
                payload_tl = await _fetch_user_tweets(
                    user_obj.get("id", ""),
                    bearer=cfg.bearer_token or "",
                    limit=cap,
                    timeout=cfg.timeout,
                    exclude_rt=cfg.exclude_retweets,
                )
            # normaliser et mettre en cache par token
            for it in _normalize_from_timeline(payload_tl, user=user_obj, token=selected_token):
                tid = str(it.get("id"))
                if tid and tid not in {x.get("id") for x in cached_items if isinstance(x, dict)}:
                    new_items.append(it)
            from contextlib import suppress

            with suppress(Exception):
                _cache_path_token(selected_token).write_text(
                    json.dumps(
                        {"ts": int(time.time()), "token": selected_token, "items": new_items},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        else:
            # hashtag → search si autorisé
            if not cfg.disable_search:
                q = _build_query(selected_token, use_lang=cfg.use_lang_filter, exclude_rt=cfg.exclude_retweets)
                payload = await _fetch_one(q, bearer=cfg.bearer_token or "", limit=cap, timeout=cfg.timeout)
                if payload is None:
                    search_disabled_dynamic = True
                for it in _normalize_items(payload, token=selected_token):
                    tid = str(it.get("id"))
                    if tid and tid not in {x.get("id") for x in cached_items if isinstance(x, dict)}:
                        new_items.append(it)
                from contextlib import suppress

                with suppress(Exception):
                    _cache_path_token(selected_token).write_text(
                        json.dumps(
                            {"ts": int(time.time()), "token": selected_token, "items": new_items},
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )

        # Mettre à jour quotas (on considère l'appel consommé même si vide)
        next_app = now + max(60, cfg.rate_window_app_sec)
        next_tok = now + max(60, cfg.rate_window_token_sec)
        token_next_map[selected_token] = next_tok
        rr_next = None
        if (cfg.selector or "").lower() == "roundrobin" and sel_index is not None:
            rr_next = (sel_index + 1) % max(1, len(wl))
        _quota_save(next_app, token_next=token_next_map, rr_index=rr_next)

    # Fusionner items: cache existant + nouveaux
    items = list(cached_items)
    # On ajoute en fin les nouveaux pour préserver ordre approximatif
    for it in new_items:
        tid = str(it.get("id"))
        if tid and tid not in {x.get("id") for x in items if isinstance(x, dict)}:
            items.append(it)

    out = {
        "ts": int(time.time()),
        "queries": 1 if selected_token else 0,
        "items": items,
        "meta": {
            "watchlist": wl,
            "limit": cap,
            "cached": False,
            "source": "x",
            "search_disabled": cfg.disable_search,
            "lang_filter": cfg.use_lang_filter,
            "exclude_retweets": cfg.exclude_retweets,
            "search_disabled_dynamic": search_disabled_dynamic,
            "pacing_ms": cfg.pacing_ms,
            "rate_window_app_sec": cfg.rate_window_app_sec,
            "rate_window_token_sec": cfg.rate_window_token_sec,
            "selected_token": selected_token,
            "quota_app_next_ts": int((_quota_load().get("app") or {}).get("next_ts", 0)),
        },
    }
    from contextlib import suppress

    with suppress(Exception):
        cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def write_export(data: dict[str, Any], *, out_dir: str = "exports/social", name: str = "latest_x_curated.json") -> str:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    dest = p / name
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(dest)
