"use client";

import { useEffect, useState } from "react";
import { Check, Copy, ExternalLink } from "lucide-react";
import { useAccount } from "@/application/useAccount";
import { useApiKeys } from "@/application/useApiKeys";
import { useAuthSession } from "@/application/useAuthSession";
import type { AccountResponse, ApiKeySummary } from "@/domain/entities";
import { PLAN_CARDS, isUpgrade } from "@/domain/plans";
import { formatDate } from "@/components/format";

/* The account tab. Four shapes, decided top-down from what the deployment and
   the caller are:

   1. No identity provider (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` unset): the
      deployment's limits, from `/api/me`, and a line saying accounts are not
      set up here. No sign-in button — there is nothing to sign in to.
   2. Provider, signed out: the same limits plus a sign-in button.
   3. Signed in, no durable storage on the backend: identity and the limits;
      no workspace, no plans, no keys, because the backend has nowhere to keep
      them. `/api/me` says so via `accounts_enabled`.
   4. Signed in with storage: workspace, usage, the plan cards (with upgrade
      buttons only when `billing_enabled`), and API keys when the plan has
      them.

   Every sentence about a limit comes from `/api/me`, never from the static
   plan table: the table is what a card promises, the response is what the
   server will enforce. */

function minutes(seconds: number): string {
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${Math.round(seconds / 6) / 10} min`;
}

function LimitsLine({ account }: { account: AccountResponse }) {
  const { usage } = account;
  return (
    <p className="prose">
      On this deployment a single video can run up to <strong>{minutes(usage.max_duration_seconds)}</strong>
      {usage.minutes_included > 0 && (
        <>
          , with <strong>{usage.minutes_included} minutes</strong> of media included each period
        </>
      )}
      . Bring-your-own-key runs are never metered.
    </p>
  );
}

function UsageMeter({ account }: { account: AccountResponse }) {
  const { usage } = account;
  if (usage.minutes_included <= 0) return null;
  const fraction = Math.min(usage.minutes_used / usage.minutes_included, 1);
  const used = Math.round(usage.minutes_used * 10) / 10;
  return (
    <div className="usage">
      <div className="usage-head">
        <span className="card-label !m-0">usage this period</span>
        <span className="usage-figure">
          {used} / {usage.minutes_included} min
        </span>
      </div>
      <div
        className="usage-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={usage.minutes_included}
        aria-valuenow={Math.min(used, usage.minutes_included)}
        aria-label="Minutes used this period"
      >
        <span className="usage-fill" style={{ width: `${fraction * 100}%` }} />
      </div>
      <p className="pending-note">
        Resets {formatDate(usage.period_end)}
        {usage.overage_usd_per_minute != null &&
          ` · after that, $${usage.overage_usd_per_minute.toFixed(2)} per extra minute`}
      </p>
    </div>
  );
}

function PlanCards({
  account,
  onUpgrade,
  busy,
}: {
  account: AccountResponse;
  onUpgrade: (plan: "pro" | "studio" | "scale") => void;
  busy: boolean;
}) {
  const current = account.usage.plan;
  return (
    <ul className="plan-grid" aria-label="Plans">
      {PLAN_CARDS.map((card) => {
        const isCurrent = card.plan === current;
        const canBuy = account.billing_enabled && card.plan !== "free" && isUpgrade(current, card.plan);
        return (
          <li key={card.plan} className="plan-card" data-current={isCurrent ? "true" : undefined}>
            <div className="plan-head">
              <span className="plan-name">{card.name}</span>
              <span className="plan-price">{card.priceUsd === 0 ? "free" : `$${card.priceUsd}/mo`}</span>
            </div>
            <ul className="plan-perks">
              {card.perks.map((perk) => (
                <li key={perk}>{perk}</li>
              ))}
            </ul>
            {isCurrent ? (
              <span className="pending-note">current plan</span>
            ) : canBuy ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => onUpgrade(card.plan as "pro" | "studio" | "scale")}
                aria-disabled={busy || undefined}
              >
                {busy ? "opening…" : `upgrade to ${card.name.toLowerCase()}`}
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function SecretReveal({ secret, name, onDismiss }: { secret: string; name: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const handle = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(handle);
  }, [copied]);
  const copy = () => {
    navigator.clipboard?.writeText(secret).then(() => setCopied(true));
  };
  return (
    <div className="key-secret" role="status">
      <p>
        <strong>{name}</strong> is ready. Copy it now — this is the only time it is shown; the server
        keeps only a hash.
      </p>
      <code className="key-secret-value">{secret}</code>
      <div className="apikey-actions">
        <button type="button" className="btn btn-secondary" onClick={copy} data-state={copied ? "copied" : undefined}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? "copied" : "copy"}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDismiss}>
          done
        </button>
      </div>
    </div>
  );
}

function KeyRow({ apiKey, onRevoke, busy }: { apiKey: ApiKeySummary; onRevoke: () => void; busy: boolean }) {
  const revoked = apiKey.revoked_at != null;
  return (
    <li className="key-row" data-revoked={revoked ? "true" : undefined}>
      <span className="h-text">
        <span className="h-title">{apiKey.name}</span>
        <span className="h-sub">
          {apiKey.prefix}… · created {formatDate(apiKey.created_at)}
          {apiKey.last_used_at && ` · last used ${formatDate(apiKey.last_used_at)}`}
          {revoked && " · revoked"}
        </span>
      </span>
      {!revoked && (
        <button type="button" className="text-link" onClick={onRevoke} aria-disabled={busy || undefined}>
          revoke
        </button>
      )}
    </li>
  );
}

function ApiKeysSection({ enabled }: { enabled: boolean }) {
  const { keys, error, busy, create, revoke, justCreated, dismissSecret } = useApiKeys(enabled);
  const [name, setName] = useState("");
  if (!enabled) return null;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void create(name).then(() => setName(""));
  };
  return (
    <section className="account-section" aria-label="API keys">
      <p className="card-label">api keys</p>
      <p className="prose">
        A key lets scripts and the VideoLens MCP server run analyses on this workspace&apos;s plan.
        Send it as an <strong>X-Api-Key</strong> header, or set <strong>VIDEOLENS_API_KEY</strong> for
        the MCP server.
      </p>
      {justCreated && (
        <SecretReveal secret={justCreated.secret} name={justCreated.name} onDismiss={dismissSecret} />
      )}
      {error && (
        <p role="alert" className="error-note">
          {error.message}
        </p>
      )}
      <form className="key-create" onSubmit={submit}>
        <label htmlFor="api-key-name" className="card-label !m-0">
          new key
        </label>
        <input
          id="api-key-name"
          className="field"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="what will use it (e.g. claude code)"
          maxLength={80}
          autoComplete="off"
        />
        <button type="submit" className="btn btn-primary" aria-disabled={busy || undefined}>
          create
        </button>
      </form>
      {keys === null ? (
        <p role="status" className="pending-note">
          Loading…
        </p>
      ) : keys.length === 0 ? (
        <p className="pending-note">No keys yet.</p>
      ) : (
        <ul className="key-list">
          {keys.map((apiKey) => (
            <KeyRow key={apiKey.key_id} apiKey={apiKey} busy={busy} onRevoke={() => void revoke(apiKey.key_id)} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function AccountPanel() {
  const auth = useAuthSession();
  const { account, error, reload, upgrade, manageBilling, busy, actionError } = useAccount(auth.user?.id ?? null);

  /* Back from Stripe: the webhook has usually landed by the time the browser
     returns, but not always. The mount fetch covers the usual case; the
     "reload" line below covers the rest. Read once, lazily, so the value is
     settled before the first render rather than set from an effect; the
     param is then scrubbed from the URL so a refresh does not re-announce. */
  const [checkoutOutcome] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("checkout");
  });
  useEffect(() => {
    if (!checkoutOutcome) return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has("checkout")) return;
    params.delete("checkout");
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/?${qs}` : "/?view=account");
  }, [checkoutOutcome]);

  if (error)
    return (
      <div role="alert" className="error-inline">
        <p>{error.message}</p>
        <button type="button" onClick={reload} className="btn btn-secondary">
          Try again
        </button>
      </div>
    );
  if (!account || !auth.ready)
    return (
      <p role="status" className="pending-note">
        Loading…
      </p>
    );

  const signedIn = account.method !== "anonymous";

  return (
    <div className="account">
      {checkoutOutcome === "success" && (
        <p role="status" className="cap-panel-note prose">
          Thanks — your plan is updating. If it does not show below yet,{" "}
          <button type="button" className="text-link" onClick={reload}>
            reload
          </button>
          .
        </p>
      )}

      <section className="account-section" aria-label="Identity">
        <p className="card-label">{signedIn ? "signed in" : "anonymous"}</p>
        {signedIn ? (
          <div className="identity">
            <p className="prose">
              <strong>{auth.user?.name || account.email || account.subject}</strong>
              {account.email && auth.user?.name && <span className="h-sub"> · {account.email}</span>}
            </p>
            {auth.enabled && (
              <button type="button" className="btn btn-secondary" onClick={auth.signOut}>
                sign out
              </button>
            )}
          </div>
        ) : auth.enabled ? (
          <div className="identity">
            <p className="prose">
              Sign in to keep a library of every run, share a workspace, and move to a paid plan.
              Anonymous runs stay on this device and expire with the server&apos;s retention window.
            </p>
            <button type="button" className="btn btn-primary" onClick={auth.signIn}>
              sign in
            </button>
          </div>
        ) : (
          <p className="prose">
            Accounts are not set up on this deployment. Runs are scoped to this browser and expire
            with the server&apos;s retention window; paste your own Gemini key under{" "}
            <strong>api key</strong> to lift the shared quota.
          </p>
        )}
        <LimitsLine account={account} />
      </section>

      {signedIn && !account.accounts_enabled && (
        <p className="pending-note">
          This deployment has no durable storage, so there is no workspace or plan to show — your
          history is the same recent list an anonymous caller gets.
        </p>
      )}

      {account.workspace && (
        <section className="account-section" aria-label="Workspace">
          <p className="card-label">workspace</p>
          <p className="prose">
            <strong>{account.workspace.name}</strong> · {account.workspace.plan} plan ·{" "}
            {account.workspace.seats} {account.workspace.seats === 1 ? "seat" : "seats"}
          </p>
          <UsageMeter account={account} />
          {account.workspace.has_subscription && account.billing_enabled && (
            <button
              type="button"
              className="text-link gap-1 inline-flex items-center"
              onClick={() => void manageBilling()}
              aria-disabled={busy === "portal" || undefined}
            >
              {busy === "portal" ? "opening billing…" : "manage billing, invoices and cancellation"}
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </section>
      )}

      {account.accounts_enabled && signedIn && (
        <section className="account-section" aria-label="Plans">
          <p className="card-label">plans</p>
          {!account.billing_enabled && (
            <p className="pending-note">Paid plans are not available on this deployment yet.</p>
          )}
          {actionError && (
            <p role="alert" className="error-note">
              {actionError.message}
            </p>
          )}
          <PlanCards account={account} onUpgrade={(plan) => void upgrade(plan)} busy={busy === "checkout"} />
        </section>
      )}

      <ApiKeysSection enabled={account.api_access && signedIn && account.account_id != null} />
    </div>
  );
}
