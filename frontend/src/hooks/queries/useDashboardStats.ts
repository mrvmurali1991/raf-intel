/**
 * useDashboardStats
 * -----------------
 * Fetches the dashboard landing stats and trends.
 *
 *   GET /api/dashboard/stats
 *   GET /api/dashboard/trends
 *   GET /api/dashboard/insights
 *
 * Usage:
 *   const { data, isLoading, isError } = useDashboardStats();
 *   const { data: trends } = useDashboardTrends();
 *   const { data: insights } = useDashboardInsights();
 */

import { useQuery } from "@tanstack/react-query";
import {
  getDashboardStats,
  getDashboardTrends,
  getDashboardInsights,
} from "@/lib/api";
import type { DashboardTrends } from "@/lib/api";
import type { DashboardStats } from "@/types";

export const DASHBOARD_STATS_QUERY_KEY = ["dashboard-stats"] as const;
export const DASHBOARD_TRENDS_QUERY_KEY = ["dashboard-trends"] as const;
export const DASHBOARD_INSIGHTS_QUERY_KEY = ["dashboard-insights"] as const;

export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: DASHBOARD_STATS_QUERY_KEY,
    queryFn: getDashboardStats,
  });
}

export function useDashboardTrends() {
  return useQuery<DashboardTrends>({
    queryKey: DASHBOARD_TRENDS_QUERY_KEY,
    queryFn: getDashboardTrends,
  });
}

export function useDashboardInsights() {
  return useQuery({
    queryKey: DASHBOARD_INSIGHTS_QUERY_KEY,
    queryFn: getDashboardInsights,
  });
}
