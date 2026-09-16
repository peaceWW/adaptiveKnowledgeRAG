/** 问答 / 图谱 / 目录共用：证据按 图 → 公式 → 表 → 说明 排序。 */
export type EvidenceLike = {
  kind?: string;
  image_key?: string;
  image_url?: string;
  role?: string;
  semantic_role?: string;
};

export function evidenceKindRank(item: EvidenceLike): number {
  const kind = String(item?.kind || "").toLowerCase();
  if (kind === "figure" || item?.image_key || item?.image_url) return 0;
  if (kind === "equation" || item?.role === "formula" || item?.semantic_role === "formula") return 1;
  if (kind === "table") return 2;
  return 3;
}

export function sortEvidence<T extends EvidenceLike>(items: T[]): T[] {
  return [...items].sort((a, b) => evidenceKindRank(a) - evidenceKindRank(b));
}

export function isFigureEvidence(item: EvidenceLike): boolean {
  return evidenceKindRank(item) === 0;
}

export function isEquationEvidence(item: EvidenceLike): boolean {
  return evidenceKindRank(item) === 1;
}
