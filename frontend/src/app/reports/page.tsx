"use client";

import { FileText } from "lucide-react";

import { usePreferences } from "../../lib/preferences";
import { Card, EmptyState, PageHeader } from "../../components/ui";

export default function ReportsPage() {
  const { t } = usePreferences();
  return (
    <div className="space-y-5">
      <PageHeader
        title={t.reports.title}
        subtitle={t.reports.subtitle}
      />
      <Card>
        <EmptyState
          icon={FileText}
          title={t.common.comingSoon}
          message={t.reports.message}
        />
      </Card>
    </div>
  );
}
