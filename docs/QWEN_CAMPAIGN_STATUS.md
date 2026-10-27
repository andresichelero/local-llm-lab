# Qwen3.5 final campaign

**Protocol:** `qwen-quant-harness-optimization-final`
**Local output:** `/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final`
**Campaign checkout:** `D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2`
**Status:** the qualification stage was started on 2026-10-27; consult the live output for current progress.

The campaign evaluates five GGUF variants each for Qwen3.5-4B and Qwen3.5-9B. They are Unsloth conversions of the base models, not additional model families. Each catalog entry records its source, revision, file hashes, tokenizer and template information as available.

| Model | Selected quantizations |
|---|---|
| Qwen3.5-4B | Q5_K_S, Q5_K_M, UD-Q5_K_XL, Q6_K, Q8_0 |
| Qwen3.5-9B | Q4_K_M, Q5_K_S, Q5_K_M, UD-Q5_K_XL, Q6_K |

All selected files are smaller than 7,500,000,000 bytes. The 9B Q6_K is close to that limit at 7,458,301,152 bytes. Size alone does not include runtime buffers, KV cache or other applications. The runner requests all layers on the GPU, disables automatic fitting and checks a 512 MiB device reserve. A configuration that cannot satisfy its capacity checks is blocked or deferred rather than counted as a reasoning failure. These controls do not prove that desktop contention cannot occur between telemetry samples.

All variants are nominally above four bits except 9B Q4_K_M, which the user expressly permitted after local GGUF tensor inspection reported 5.0656 bits per element across 427 tensors. The file contains a mixture of F32, Q4_K, Q5_K, Q6_K and Q8_0 tensors. The figure is an average across tensor elements, not a claim that every tensor is above four bits.

## Additional formats

The earlier EXL3 catalog contained 9B variants through 6 bits per weight. Its 2–4 bpw variants are below or equal to the strict four-bit floor, while the 5–6 bpw files exceed 7.5 GB; none enters the final queue under these constraints. No 4B EXL3 artifact was present in that catalog. AWQ, GPTQ, FP8, MNN, OpenVINO, MLX and raw Hugging Face formats are not currently qualified as compatible by this runner and are not included. A new candidate needs separate provenance, compatibility and capacity checks before entering a new frozen protocol.

## Evidence and selection

Qualification uses twelve checks with a 10/12 floor. Eligible candidates advance to the separately recorded context/capacity and development tasks. Selection is not a throughput-only ranking: task completion, useful context, elapsed time and memory evidence matter. The schedule can grow as gates pass. Model errors remain model results; resource, transport, tool and infrastructure problems are recorded separately.

Twenty-two completed historical attempts for selected artifacts were copied with their original protocol identifiers and raw evidence to `reference-selected` under the final output. The 1,015 copied evidence files were hash-verified; the bundle is historical reference and is not silently mixed into the new-protocol ranking. Blocked attempts without reusable model results were excluded. Old campaign result directories and unselected model-cache objects were removed at the user's request.

The planned comparison of coding harnesses and reasoning-off/low/medium profiles remains a later stage. It is not yet an automatic continuation of `final`: the older native harness runner references the removed v4 output and requires adaptation and offline validation under its own protocol before use. No harness winner or final quantization winner has been established.

## Local operation and limitations

The current local implementation resides in the separate campaign checkout and includes uncommitted/untracked files not supplied by this documentation-only branch. The final service is `qwen-quant-optimization-final.service`; status queries must specify the final output and confirm the service directly because the older status helper can display a stale service name. The monitor is scheduled every 30 minutes to investigate and safely recover confirmed infrastructure failures, while preserving final evidence and avoiding retries of completed model failures.

The offline foundation gate completed with 186 tests, lint and compilation before inference. A focused set of 16 wrapper, catalog and retention tests also passed; these sets overlap. No tests or graders were run concurrently with inference.
