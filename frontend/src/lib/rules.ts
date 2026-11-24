/** Rule JSON, mirroring SPEC §8.2. */

export type IndOperand = { ind: string; params?: Record<string, number>; offset?: number; times?: number; rank?: boolean };
export type FundOperand = { fund: string; times?: number };
export type ValueOperand = { value: number };
export type Operand = IndOperand | FundOperand | ValueOperand;

export interface Cond {
  left: Operand;
  op: string;
  right: Operand;
}
export type AllGroup = { all: Node[] };
export type AnyGroup = { any: Node[] };
export type NotGroup = { not: Node };
export type Group = AllGroup | AnyGroup | NotGroup;
export type Node = Cond | Group;
export type Rule = Group;

export const MAX_DEPTH = 4;
export const MAX_CONDITIONS = 20;

export function isCond(n: Node): n is Cond {
  return "op" in n;
}

export function emptyCondition(): Cond {
  return { left: { ind: "close" }, op: ">", right: { ind: "sma", params: { n: 50 } } };
}

export function emptyRule(): Rule {
  return { all: [emptyCondition()] };
}

export function countConditions(n: Node): number {
  if (isCond(n)) return 1;
  if ("not" in n) return countConditions(n.not);
  return ("all" in n ? n.all : n.any).reduce((sum, c) => sum + countConditions(c), 0);
}

/** Nesting depth the way the server counts it: every group, including NOT, is one level. */
export function depthOf(n: Node, level = 1): number {
  if (isCond(n)) return level - 1;
  const kids = "not" in n ? [n.not] : "all" in n ? n.all : n.any;
  return Math.max(level, ...kids.map((k) => depthOf(k, level + 1)));
}

export function withinLimits(n: Node): boolean {
  return depthOf(n) <= MAX_DEPTH && countConditions(n) <= MAX_CONDITIONS;
}
