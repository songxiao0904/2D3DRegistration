from utils import CE, crop_image, dice_loss
from sklearn.metrics import confusion_matrix
import os
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
import ConvNet
import dataloader
import torch.optim as optim
import numpy as np
import torch
import torch.nn as nn
import utils
import visdom
from dataloader import SegData_csv
from torchvision import transforms
from torch.utils.data import DataLoader
import cv2
import argparse


def transform(img):
    max_value = img.max()
    img_tensor = torch.from_numpy(img.astype(np.int32))
    img_tensor = img_tensor.float() / max_value
    return img_tensor


def train(net, loader, optimizer, drr_win, xray_win, env):
    train_loss = 0.0
    num = 0
    net.train()

    for i, data in enumerate(loader, 0):
        # inputs and labels.
        inputs = data[0]
        inputs_X = data[1]
        inputs, inputs_X, labels = inputs.cuda(), inputs_X.cuda(), data[2].cuda()
        # Set the gradient to be 0.
        optimizer.zero_grad()

        # Train -> Back propagation -> Optimization.
        outputs = net(inputs, inputs_X)

        drr = utils.DRR_generation(data[0].view(1, inputs.shape[2], inputs.shape[3], inputs.shape[4]), outputs, train_batch_num, proj_pix).view((1, proj_pix[0], proj_pix[1]))
        loss = mse(outputs, labels) + alpha * mse(drr, data[1].cuda(1))

        loss.backward()
        optimizer.step()
        #
        # # tt = drr[0].cpu().numpy().squeeze()
        # tt = data[1][0].cpu().numpy().squeeze()
        # if (tt.max() != tt.min()):
        #     tt = (tt - tt.min()) / (tt.max() - tt.min())
        # cv2.imshow('img', tt)
        # cv2.waitKey(10)


        xray_win = utils.PlotImage(vis=vis, img=data[1][0].cpu().numpy().squeeze(), win=xray_win, env=env,
                                   title="Train X-ray")
        drr_win = utils.PlotImage(vis=vis, img=drr[0].cpu().numpy().squeeze(), win=drr_win, env=env, title="Train DRR")


        train_loss += mse(outputs, labels).item() + mse(drr, data[1].cuda(1)).item()
        num += data[0].size(0)

    return train_loss / num, drr_win, xray_win


def test(net, loader, optimizer, drr_win, xray_win, env):
    test_loss = 0.0
    num = 0
    net.eval()

    for i, data in enumerate(loader, 0):
        # inputs and labels.
        inputs = data[0]
        inputs_X = data[1]
        inputs, inputs_X, labels= inputs.cuda(), inputs_X.cuda(), data[2].cuda()
        # Set the gradient to be 0.
        optimizer.zero_grad()

        # Feed forward
        outputs = net(inputs, inputs_X)

        drr = utils.DRR_generation(data[0].view(1, inputs.shape[2], inputs.shape[3], inputs.shape[4]), outputs, train_batch_num, proj_pix).view((1, proj_pix[0], proj_pix[1]))
        loss = mse(outputs, labels) + mse(drr, data[1].cuda(1))

        xray_win = utils.PlotImage(vis=vis, img=data[1][0].cpu().numpy().squeeze(), win=xray_win, env=env,
                                   title="Test X-ray")
        drr_win = utils.PlotImage(vis=vis, img=drr[0].cpu().numpy().squeeze(), win=drr_win, env=env, title="Test DRR")

        test_loss += loss.item()
        num += data[0].size(0)

    return test_loss / num, drr_win, xray_win


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preocess some numbers.")
    parser.add_argument('--net', type=str, help='Network architecture, 6layer, 8layer, unet', default='6layer')
    parser.add_argument('--alpha', type=float, help='alpha', default=1e-4)
    parser.add_argument('--lr', type=float, help='Learning rate', default=1e-3)
    parser.add_argument('--gpu', type=str, help='gpu number', default='2, 3')

    args = parser.parse_args()

    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu

    env = "seg_" + args.net + "_alpha_" + str(args.alpha) + "lr_" + str(args.lr)

    train_file = './train_256.csv'
    test_file = './test_256.csv'
    PATH = './saved/'
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vis = visdom.Visdom()

    train_batch_num = 1
    alpha = args.alpha

    proj_pix = [256, 256]

    mse = torch.nn.MSELoss()

    # train_win = vis.line(Y=torch.randn(1), X=np.array([5]), opts=dict(title="Train"))
    # test_win = vis.line(Y=torch.randn(1), X=np.array([5]), opts=dict(title="Test"))
    loss_win = None
    train_drr_win = None
    test_drr_win = None
    train_xray_win = None
    test_xray_win = None

    transfroms_ = transforms.Compose([
        transforms.ToTensor(),
        # transforms.Resize((64, 64))
    ])
    train_dataset = SegData_csv(train_file, proj_pix, transform=transfroms_)
    test_dataset = SegData_csv(test_file, proj_pix, transform=transfroms_)
    trainloader = DataLoader(train_dataset, batch_size=train_batch_num, shuffle=True, num_workers=0)
    testloader = DataLoader(test_dataset, batch_size=train_batch_num, shuffle=False, num_workers=0)
    if args.net == '6layer':
        net = ConvNet.layer6Net(1, 20, 6)
    elif args.net == '8layer':
        net = ConvNet.layer8Net(1, 20, 6)
    else:
        net = ConvNet.UNet(1, 20, 6)

    net = net.cuda()
    net = nn.DataParallel(net)

    criterion = torch.nn.MSELoss()
    optimizer = optim.Adam(net.parameters(), lr=args.lr, weight_decay=1e-4)
    # train_scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=300)

    best_loss = np.inf


    # vis.close(env="seg_6layer")
    if os.path.isfile("./saved/BEST" + env[3:] + ".pth"):
        ck = torch.load("./saved/BEST" + env[3:] + ".pth")
        net.load_state_dict(ck['state_dict'])
        optimizer.load_state_dict(ck['optimizer'])
        start = ck['epoch']
        best_loss = ck['best_loss']
    else:
        start = 0
    for epoch in range(start, 200):
        train_loss, train_drr_win, train_xray_win = train(net, trainloader, optimizer, train_drr_win, train_xray_win,
                                                          env)
        test_loss, test_drr_win, test_xray_win = test(net, testloader, optimizer, test_drr_win, test_xray_win, env)
        # train_scheduler.step(epoch)

        # train_loss_win = utils.PlotLoss(vis=vis, x=torch.tensor([epoch]), y=torch.tensor([train_loss]), win=train_loss_win, env=env,
        #                           title="Train Loss")
        # test_loss_win = utils.PlotLoss(vis=vis, x=torch.tensor([epoch]), y=torch.tensor([test_loss]), win=test_loss_win, env=env,
        #                           title="Test Loss")

        x = torch.tensor([epoch + 1, epoch + 1]).view((-1, 2))
        y = torch.tensor([train_loss, test_loss]).view((-1, 2))
        loss_win = utils.PlotLoss(vis=vis, x=x, y=y, win=loss_win, env=env, legend=['Train', 'Test'],
                                  title="Loss")

        print('%d train loss: %.3f, test loss: %.3f' % (epoch + 1, train_loss, test_loss))
        is_best = test_loss < best_loss
        best_loss = min(test_loss, best_loss)
        if is_best:
            torch.save({
                'epoch': epoch + 1,
                'state_dict': net.state_dict(),
                'best_loss': best_loss,
                'optimizer': optimizer.state_dict(),
            }, PATH + "BEST" + env[3:] + ".pth")

    print('Finished Training')