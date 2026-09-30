export interface EmbeddingContract {
  model: string;
  dimensions: number;
}

export const EMBEDDED_TYPES: readonly string[] = ['Passage', 'Note', 'Topic'];

export class ContractError extends Error {}

export function parseContract(text: string): EmbeddingContract {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new ContractError('the embedding contract is not JSON');
  }
  const candidate = parsed as { model?: unknown; dimensions?: unknown };
  if (typeof candidate.model !== 'string' || candidate.model.length === 0) throw new ContractError('the embedding contract names no model');
  if (typeof candidate.dimensions !== 'number' || !Number.isInteger(candidate.dimensions) || candidate.dimensions <= 0) {
    throw new ContractError('the embedding contract names no dimensions');
  }
  return { model: candidate.model, dimensions: candidate.dimensions };
}

export interface EmbedDeclaration {
  type: string;
  dimensions: number;
  model: string;
}

export function embedDeclarations(schemaSource: string): EmbedDeclaration[] {
  const declarations: EmbedDeclaration[] = [];
  const node = /node\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([^}]*)\}/g;
  for (const match of schemaSource.matchAll(node)) {
    const body = match[2]!;
    const embed = /Vector\((\d+)\)\??\s*@embed\(\s*"[^"]*"\s*,\s*model\s*=\s*"([^"]+)"\s*\)/.exec(body);
    if (embed !== null) declarations.push({ type: match[1]!, dimensions: Number(embed[1]), model: embed[2]! });
  }
  return declarations;
}

export interface ContractVerdict {
  ok: boolean;
  reason: string | null;
}

export function checkContract(contract: EmbeddingContract, schemaSource: string): ContractVerdict {
  const declared = new Map(embedDeclarations(schemaSource).map((declaration) => [declaration.type, declaration]));
  for (const type of EMBEDDED_TYPES) {
    const declaration = declared.get(type);
    if (declaration === undefined) return { ok: false, reason: `the schema declares no @embed vector on ${type}` };
    if (declaration.model !== contract.model) return { ok: false, reason: `${type} embeds with another model than the contract` };
    if (declaration.dimensions !== contract.dimensions) return { ok: false, reason: `${type} vectors have other dimensions than the contract` };
  }
  return { ok: true, reason: null };
}
