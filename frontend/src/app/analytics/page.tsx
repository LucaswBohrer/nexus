"use client";

import { BarChart3 } from "lucide-react";

import { usePreferences } from "../../lib/preferences";
import { Card, EmptyState, PageHeader } from "../../components/ui";

export default function AnalyticsPage() {
  const { t } = usePreferences();
  return (
    <div className="space-y-5">
      <PageHeader
        title={t.analytics.title}
        subtitle={t.analytics.subtitle}
      />
      <Card>
        <EmptyState
          icon={BarChart3}
          title={t.common.comingSoon}
          message={t.analytics.message}
        />
      </Card>
    </div>
  );
}
