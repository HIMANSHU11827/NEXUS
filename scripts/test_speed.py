import torch
import time

x = torch.randn(1024, 1024)
y = torch.randn(1024, 1024)

start = time.time()
for _ in range(100):
    z = torch.matmul(x, y)
end = time.time()

print(f"100 Matmuls took {end-start:.2f} seconds.")
