"use client";

import { useCallback, useEffect, useState } from "react";
import type { ApiKeyCreated, ApiKeySummary } from "@/domain/entities";
import { classifyGatewayError, type GatewayError } from "@/application/gatewayError";
import { accountGateway } from "@/infrastructure/container";

/**
 * A workspace's API keys. Only mounted when `/api/me` says the plan includes
 * API access, so the 403 the backend would otherwise answer never renders.
 *
 * `justCreated` holds the one response that carries a secret. It lives in
 * React state and nowhere else — not localStorage, not the list — and is
 * cleared the moment the panel dismisses it. The server keeps only a hash,
 * so once it is gone the only recovery is a new key.
 */
export function useApiKeys(enabled: boolean) {
  const [keys, setKeys] = useState<ApiKeySummary[] | null>(null);
  const [error, setError] = useState<GatewayError | null>(null);
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    accountGateway
      .listKeys()
      .then((response) => {
        if (cancelled) return;
        setKeys(response.keys);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(classifyGatewayError(err, "API keys could not be loaded."));
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const create = useCallback(
    async (name: string) => {
      if (busy) return;
      setBusy(true);
      setError(null);
      try {
        const created = await accountGateway.createKey(name);
        setJustCreated(created);
        setKeys((current) => [created, ...(current ?? [])]);
      } catch (err) {
        setError(classifyGatewayError(err, "The API key could not be created."));
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  const revoke = useCallback(
    async (keyId: string) => {
      if (busy) return;
      setBusy(true);
      setError(null);
      try {
        await accountGateway.revokeKey(keyId);
        const now = new Date().toISOString();
        setKeys((current) =>
          (current ?? []).map((key) => (key.key_id === keyId ? { ...key, revoked_at: now } : key)),
        );
        setJustCreated((current) => (current?.key_id === keyId ? null : current));
      } catch (err) {
        setError(classifyGatewayError(err, "The API key could not be revoked."));
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  const dismissSecret = useCallback(() => setJustCreated(null), []);

  return { keys, error, busy, create, revoke, justCreated, dismissSecret };
}
