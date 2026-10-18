"""Trains the square classifier and exports it for numpy inference (development tool).

    python tools/vision_train.py --data data/squares.npz --out cbv/vision/pieces.onnx

Needs PyTorch and onnx (``pip install torch --index-url https://download.pytorch.org/whl/cpu``,
``pip install onnx onnxscript``); the app runs the exported ONNX model with OpenCV.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

CLASSES = ".PNBRQKpnbrqk"


def build() -> nn.Sequential:
    def block(cin, cout):
        return [nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(), nn.MaxPool2d(2)]

    return nn.Sequential(
        *block(1, 24), *block(24, 48), *block(48, 96),
        nn.Flatten(), nn.Linear(96 * 16, 128), nn.ReLU(), nn.Dropout(0.3), nn.Linear(128, len(CLASSES)),
    )


def augment(x: torch.Tensor) -> torch.Tensor:
    """Mirror (a mirrored knight is still a knight), shift a little, vary contrast."""
    flip = torch.rand(x.shape[0]) < 0.5
    x = torch.where(flip[:, None, None, None], x.flip(3), x)
    pad = nn.functional.pad(x, (2, 2, 2, 2), value=1.0)
    dy, dx = np.random.randint(0, 5, 2)
    x = pad[:, :, dy:dy + 32, dx:dx + 32]
    gain = torch.empty(x.shape[0], 1, 1, 1).uniform_(0.8, 1.15)
    return (1 - (1 - x) * gain).clamp(0, 1)


def export(model: nn.Sequential, path: Path) -> None:
    """Saves the model as ONNX (run by OpenCV in the app), batch norm folded into the convolutions."""
    weights = {}
    convs = [m for m in model if isinstance(m, nn.Conv2d)]
    norms = [m for m in model if isinstance(m, nn.BatchNorm2d)]
    for i, (conv, bn) in enumerate(zip(convs, norms), 1):
        scale = bn.weight / torch.sqrt(bn.running_var + bn.eps)
        weights[f"c{i}w"] = (conv.weight * scale[:, None, None, None]).detach()
        weights[f"c{i}b"] = ((conv.bias - bn.running_mean) * scale + bn.bias).detach()
    for i, lin in enumerate([m for m in model if isinstance(m, nn.Linear)], 1):
        weights[f"f{i}w"], weights[f"f{i}b"] = lin.weight.detach(), lin.bias.detach()
    save_onnx(weights, path)


def save_onnx(weights: dict[str, torch.Tensor], path: Path) -> None:
    def block(cin, cout):
        return [nn.Conv2d(cin, cout, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2)]

    plain = nn.Sequential(*block(1, 24), *block(24, 48), *block(48, 96), nn.Flatten(),
                          nn.Linear(96 * 16, 128), nn.ReLU(), nn.Linear(128, len(CLASSES)), nn.Softmax(1))
    with torch.no_grad():
        for i, conv in enumerate([m for m in plain if isinstance(m, nn.Conv2d)], 1):
            conv.weight.copy_(weights[f"c{i}w"])
            conv.bias.copy_(weights[f"c{i}b"])
        for i, lin in enumerate([m for m in plain if isinstance(m, nn.Linear)], 1):
            lin.weight.copy_(weights[f"f{i}w"])
            lin.bias.copy_(weights[f"f{i}b"])
    plain.eval()
    torch.onnx.export(plain, torch.zeros(1, 1, 32, 32), str(path), input_names=["squares"], output_names=["probabilities"],
                      dynamic_axes={"squares": {0: "n"}, "probabilities": {0: "n"}}, opset_version=13, dynamo=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--convert", type=Path, help="only convert folded weights saved as .npz to ONNX")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4, help="more than the physical cores slows training down")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()
    if args.convert:
        with np.load(args.convert) as w:
            save_onnx({k: torch.from_numpy(w[k]) for k in w.files}, args.out)
        return
    torch.manual_seed(0)
    torch.set_num_threads(args.threads)
    np.random.seed(0)

    d = np.load(args.data)
    x = torch.from_numpy(d["x"]).float().div(255).unsqueeze(1)
    y = torch.from_numpy(d["y"].astype(np.int64))
    perm = torch.randperm(len(y))
    n_val = len(y) // 20
    val, train = perm[:n_val], perm[n_val:]
    print(f"{len(train)} training squares, {n_val} for validation", flush=True)

    model = build()
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    steps = args.epochs * (len(train) // args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=steps)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.05)

    for epoch in range(args.epochs):
        t = time.time()
        model.train()
        order = train[torch.randperm(len(train))]
        total = 0.0
        for i in range(len(train) // args.batch):
            idx = order[i * args.batch:(i + 1) * args.batch]
            loss = loss_fn(model(augment(x[idx])), y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            total += loss.item()
        model.eval()
        with torch.no_grad():
            pred = torch.cat([model(x[val[i:i + 2048]]).argmax(1) for i in range(0, n_val, 2048)])
        acc = (pred == y[val]).float().mean().item()
        print(f"epoch {epoch + 1}: loss {total / (len(train) // args.batch):.4f} val acc {acc:.4f} ({time.time() - t:.0f}s)", flush=True)
        export(model, args.out)  # usable after every epoch

    errors = torch.zeros(len(CLASSES), len(CLASSES), dtype=torch.long)
    for t_, p_ in zip(y[val].tolist(), pred.tolist()):
        errors[t_, p_] += 1
    for c in range(len(CLASSES)):
        row = errors[c]
        print(f"  {CLASSES[c]}: {row[c].item()}/{row.sum().item()} correct; confused with "
              + ", ".join(f"{CLASSES[j]}×{row[j].item()}" for j in row.argsort(descending=True)[:3].tolist() if j != c and row[j]))
    export(model, args.out)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
