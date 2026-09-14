from __future__ import annotations


def build_unet(in_channels: int = 3, base_channels: int = 32):
    """Create a compact U-Net for binary oil-slick segmentation.

    Imports are local so the base API remains inspectable when optional ML wheels are not installed.
    """
    import torch
    from torch import nn

    class DoubleConv(nn.Module):
        def __init__(self, input_channels: int, output_channels: int) -> None:
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv2d(input_channels, output_channels, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(output_channels),
                nn.ReLU(inplace=True),
                nn.Conv2d(output_channels, output_channels, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(output_channels),
                nn.ReLU(inplace=True),
            )

        def forward(self, values: torch.Tensor) -> torch.Tensor:
            return self.layers(values)

    class UNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            channels = (base_channels, base_channels * 2, base_channels * 4, base_channels * 8)
            self.encoder_1 = DoubleConv(in_channels, channels[0])
            self.encoder_2 = DoubleConv(channels[0], channels[1])
            self.encoder_3 = DoubleConv(channels[1], channels[2])
            self.encoder_4 = DoubleConv(channels[2], channels[3])
            self.pool = nn.MaxPool2d(kernel_size=2)
            self.bottleneck = DoubleConv(channels[3], channels[3] * 2)
            self.up_4 = nn.ConvTranspose2d(channels[3] * 2, channels[3], kernel_size=2, stride=2)
            self.decode_4 = DoubleConv(channels[3] * 2, channels[3])
            self.up_3 = nn.ConvTranspose2d(channels[3], channels[2], kernel_size=2, stride=2)
            self.decode_3 = DoubleConv(channels[2] * 2, channels[2])
            self.up_2 = nn.ConvTranspose2d(channels[2], channels[1], kernel_size=2, stride=2)
            self.decode_2 = DoubleConv(channels[1] * 2, channels[1])
            self.up_1 = nn.ConvTranspose2d(channels[1], channels[0], kernel_size=2, stride=2)
            self.decode_1 = DoubleConv(channels[0] * 2, channels[0])
            self.head = nn.Conv2d(channels[0], 1, kernel_size=1)

        def forward(self, values: torch.Tensor) -> torch.Tensor:
            encoder_1 = self.encoder_1(values)
            encoder_2 = self.encoder_2(self.pool(encoder_1))
            encoder_3 = self.encoder_3(self.pool(encoder_2))
            encoder_4 = self.encoder_4(self.pool(encoder_3))
            bottleneck = self.bottleneck(self.pool(encoder_4))
            decoder_4 = self.decode_4(torch.cat([self.up_4(bottleneck), encoder_4], dim=1))
            decoder_3 = self.decode_3(torch.cat([self.up_3(decoder_4), encoder_3], dim=1))
            decoder_2 = self.decode_2(torch.cat([self.up_2(decoder_3), encoder_2], dim=1))
            decoder_1 = self.decode_1(torch.cat([self.up_1(decoder_2), encoder_1], dim=1))
            return self.head(decoder_1)

    return UNet()
