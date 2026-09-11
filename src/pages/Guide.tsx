import { ReactNode } from 'react';
import { Card, Page, Section } from '../components/common';

/**
 * The first page a new operator reads.
 *
 * Prose is capped near 70 characters. The page container is the full window
 * width, so an unconstrained paragraph here ran about 140 characters a line
 * at 1440px -- roughly double a comfortable measure.
 */
function Prose({ children }: { children: ReactNode }) {
  return <div className="max-w-[68ch] space-y-3 text-sm leading-relaxed text-rom-muted">{children}</div>;
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-4">
      <span
        aria-hidden
        className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-rom-border bg-rom-surface2 text-[11px] font-semibold tabular-nums text-rom-muted"
      >
        {n}
      </span>
      <div className="min-w-0">
        <div className="text-sm font-medium text-white">{title}</div>
        <p className="mt-1 max-w-[62ch] text-sm leading-relaxed text-rom-muted">{children}</p>
      </div>
    </li>
  );
}

function WhatFor({ page, children }: { page: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-b border-rom-border py-3 last:border-b-0 sm:flex-row sm:gap-6">
      <div className="w-40 shrink-0 text-sm font-medium text-white">{page}</div>
      <p className="max-w-[58ch] text-sm leading-relaxed text-rom-muted">{children}</p>
    </div>
  );
}

export function GuidePage() {
  return (
    <Page title="Guide" subtitle="Get started with ROM Polybot">
      <div className="max-w-5xl space-y-8">
        <Section
          title="Connect and trade"
          description="Four steps from a fresh install to a bot you have reviewed."
        >
          <Card>
            <ol className="space-y-5">
              <Step n={1} title="Create and verify your Polymarket US account">
                Trading is only available to verified accounts on Polymarket US.
              </Step>
              <Step n={2} title="Generate a Key ID and Secret Key">
                From polymarket.us/developer. The Secret Key is shown once — keep
                it somewhere you can retrieve it.
              </Step>
              <Step n={3} title="Save them on the API page">
                Enter both values and select Save and connect. Credentials stay on
                this machine; they are never sent anywhere but Polymarket US.
              </Step>
              <Step n={4} title="Review your limits before enabling trading">
                Set your per-position cap, portfolio exposure, cash reserve and
                daily loss stop on the Strategy page. Nothing is submitted until
                you start a mode there.
              </Step>
            </ol>
          </Card>
        </Section>

        <Section
          title="Start in practice"
          description="Practice mode runs the same strategy against simulated funds."
        >
          <Card>
            <Prose>
              <p>
                Practice and live share one code path: the same signals, the same
                limits, the same sizing. The difference is that practice never
                sends an order to the exchange. Run it first — it is the cheapest
                way to find out whether the settings you chose behave the way you
                expected.
              </p>
              <p>
                Both modes are started from the Strategy page, and both are paused
                by default after install. Neither starts on its own.
              </p>
            </Prose>
          </Card>
        </Section>

        <Section title="What each page is for">
          <Card>
            <WhatFor page="Overview">
              Account value, what the strategy last decided, and the recovery
              panel if an order ever needs attention.
            </WhatFor>
            <WhatFor page="Strategy">
              Risk limits, signal thresholds, and the controls that start or
              pause practice and live trading.
            </WhatFor>
            <WhatFor page="Positions & History">
              What is open now, and what has already resolved with its result.
            </WhatFor>
            <WhatFor page="Terminal">
              A live feed of prices, signals and the backend log while the bot
              is running.
            </WhatFor>
            <WhatFor page="Crypto">
              The separate 15-minute crypto strategy, with its own switch and its
              own limits.
            </WhatFor>
            <WhatFor page="Backtest & Evidence">
              Replay a strategy over recorded history, and inspect the evidence
              behind a decision.
            </WhatFor>
            <WhatFor page="Scripts">
              Custom rules you write yourself. Each is risk-audited before it can
              be armed.
            </WhatFor>
          </Card>
        </Section>

        <Section
          title="If something goes wrong"
          description="What the bot does when it cannot be sure about an order."
        >
          <Card>
            <Prose>
              <p>
                Every order is written to a local journal before it is sent. If
                the bot cannot confirm what happened to one — a dropped
                connection at the wrong moment — it stops submitting new orders
                from every engine rather than risk duplicating a position.
              </p>
              <p>
                When that happens, a recovery panel appears on the Overview page
                naming the order and the details needed to match it against your
                order list on Polymarket US. Submissions resume once it is
                resolved. This is deliberate: it will not time out or forget on
                its own.
              </p>
            </Prose>
          </Card>
        </Section>

        <Section title="What this software does not promise">
          <Card>
            <Prose>
              <p>
                Automated trading can lose money, including more than you expect
                in a fast market. Loss limits pause new entries; they do not
                guarantee a maximum loss. Gaps, existing positions and separate
                engines can all produce further losses after a limit is hit.
              </p>
              <p>
                Market availability, fees and settlement all come from Polymarket
                US. Wallet copy trading is unavailable on the US venue; its
                controls remain visible for reference. Crypto strategies require
                matching markets to be listed.
              </p>
            </Prose>
          </Card>
        </Section>
      </div>
    </Page>
  );
}
