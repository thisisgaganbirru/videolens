"use client";

import { useCallback, useEffect, useState } from "react";
import type { ApiKeyCreated, ApiKeySummary } from "@/domain/entities";
import { classifyGatewayError, type GatewayError } from "@/application/gatewayError";
import { accountGateway } from "@/infrastructure/container";

/**
 * The signed-in person's VideoLens API keys (`/api/keys`). Mounted only when
 * `/api/me` says the server keeps accounts and there is a workspace, so the
 * 503 the backend would otherwise answer never renders.
 *
 * `justCreated` holds the one response that carries a secret. It lives in
 * React state and nowhere else (not localStorage, not the list) and is
 * cleared the moment the panel dismisses it. The server keeps only a hash,
 * so once it is gone the only recovery is a new key.
 */
export function useApiKeys(enabled: boolean) {
  const [keys, setKeys] = useState<ApiKeySummary[] | null>(null);
  const [loadError, setLoadError] = useState<GatewayError | null>(null);
  const [actionError, setActionError] = useState<GatewayError | null>(null);
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null);
  const [busy, setBusy] = useState<"create" | string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    accountGateway
      .listKeys()
      .then((response) => {
        if (cancelled) return;
        setKeys(response.keys);
        setLoadError(null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(classifyGatewayError(err, "Your API keys could not be loaded."));
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, attempt]);

  const reload = useCallback(() => {
    setLoadError(null);
    setAttempt((n) => n + 1);
  }, []);

  /** Resolves true when the key was made, so the form can clear its field. */
  const create = useCallback(
    async (name: string): Promise<boolean> => {
      if (busy) return false;
      setBusy("create");
      setActionError(null);
      try {
        const created = await accountGateway.createKey(name.trim());
        setJustCreated(created);
        /* The list gets the summary only: the secret lives in `justCreated`
           and nowhere else, so "Done" really drops it. */
        const { secret: _omit, ...summary } = created;
        void _omit;
        setKeys((current) => [summary, ...(current ?? [])]);
        return true;
      } catch (err) {
        setActionError(classifyGatewayError(err, "The key could not be created."));
        return false;
      } finally {
        setBusy(null);
      }
    },
    [busy]
  );

  const revoke = useCallback(
    async (keyId: string): Promise<boolean> => {
      if (busy) return false;
      setBusy(keyId);
      setActionError(null);
      try {
        await accountGateway.revokeKey(keyId);
        const now = new Date().toISOString();
        setKeys((current) =>
          (current ?? []).map((key) => (key.key_id === keyId ? { ...key, active: false, revoked_at: now } : key))
        );
        setJustCreated((current) => (current?.key_id === keyId ? null : current));
        return true;
      } catch (err) {
        setActionError(classifyGatewayError(err, "The key could not be revoked."));
        return false;
      } finally {
        setBusy(null);
      }
    },
    [busy]
  );

  const dismissSecret = useCallback(() => setJustCreated(null), []);

  return { keys, loadError, actionError, busy, create, revoke, reload, justCreated, dismissSecret };
}
