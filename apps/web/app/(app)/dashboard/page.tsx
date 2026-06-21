"use client";

import * as React from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusLight, type Tone } from "@/components/features/status-badge";
import { getHealth } from "@/lib/api/health";
import { getDailyTaskStats } from "@/lib/api/stats";
import type { DailyTaskCount, HealthInfo } from "@/lib/api/types";

interface ServiceRow {
  key: string;
  name: string;
  tone: Tone;
  notes: string;
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const [health, setHealth] = React.useState<HealthInfo | null>(null);
  const [buckets, setBuckets] = React.useState<DailyTaskCount[]>([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([getHealth(), getDailyTaskStats(30)])
      .then(([healthRes, statsRes]) => {
        if (!active) return;
        setHealth(healthRes);
        setBuckets(statsRes.buckets);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const serviceRows = React.useMemo<ServiceRow[]>(() => {
    const h = health;
    const rows: ServiceRow[] = [];

    // Server: the dashboard rendered health, so the server responded.
    rows.push({
      key: "server",
      name: t("health.server"),
      tone: h ? "green" : "gray",
      notes: h?.version ?? "-",
    });

    // Agent: schedulable-node scheduling health (server-computed).
    const agentStatus = h?.agent?.status;
    let agentTone: Tone = "gray";
    if (agentStatus === "green") agentTone = "green";
    else if (agentStatus === "yellow") agentTone = "amber";
    else if (agentStatus === "red") agentTone = "red";
    rows.push({
      key: "agent",
      name: t("health.agent"),
      tone: agentTone,
      notes: h?.agent
        ? t("health.agentNotes", {
            healthy: h.agent.healthy,
            schedulable: h.agent.schedulable,
          })
        : "-",
    });

    // Redis: ok -> green, error -> red, disabled/unknown -> gray.
    const redisStatus = h?.redis?.status;
    let redisTone: Tone = "gray";
    if (redisStatus === "ok") redisTone = "green";
    else if (redisStatus === "error") redisTone = "red";
    rows.push({
      key: "redis",
      name: t("health.redis"),
      tone: redisTone,
      notes:
        redisStatus === "disabled" || !redisStatus
          ? t("health.redisDisabled")
          : (h?.redis?.version ?? redisStatus),
    });

    // PostgreSQL: ok -> green else red.
    const pg = h?.postgresql?.status ?? h?.database;
    rows.push({
      key: "postgresql",
      name: t("health.postgresql"),
      tone: pg === "ok" ? "green" : "red",
      notes: h?.postgresql?.version ?? "-",
    });

    return rows;
  }, [health, t]);

  const hasActivity = buckets.some((b) => b.tasks > 0 || b.executions > 0);

  const chartConfig = {
    tasks: { label: t("health.statsTasks"), color: "var(--chart-1)" },
    executions: { label: t("health.statsExecutions"), color: "var(--chart-2)" },
  } satisfies ChartConfig;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t("health.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("health.service")}</TableHead>
                  <TableHead className="w-24">{t("health.status")}</TableHead>
                  <TableHead>{t("health.notes")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {serviceRows.map((row) => (
                  <TableRow key={row.key} data-testid={`health-${row.key}`}>
                    <TableCell>{row.name}</TableCell>
                    <TableCell>
                      <StatusLight tone={row.tone} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.notes}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("health.statsTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {!hasActivity ? (
            <div className="text-muted-foreground py-6 text-center text-sm">
              {t("health.statsEmpty")}
            </div>
          ) : (
            <ChartContainer
              config={chartConfig}
              className="max-h-[220px] w-full"
              data-testid="dashboard-chart"
            >
              <BarChart accessibilityLayer data={buckets}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                  minTickGap={24}
                  tickFormatter={(value: string) => value.slice(5)}
                />
                <ChartTooltip content={<ChartTooltipContent />} />
                <ChartLegend content={<ChartLegendContent />} />
                <Bar dataKey="tasks" fill="var(--color-tasks)" radius={2} />
                <Bar
                  dataKey="executions"
                  fill="var(--color-executions)"
                  radius={2}
                />
              </BarChart>
            </ChartContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
