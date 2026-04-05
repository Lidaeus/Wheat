ptf ^
$CULTIVARS:WHCER046.010115   Last edit:241214
 
! Coefficients used in the Cropsim-Ceres model differ from those used
! in DSSAT Versions 3.5 and 4.0. They can be calculated (approximately) from
! V3.5 coefficients as follows:
 
! P1V   = P1V(v3.5)*10
! P1D   = P1D(V3.5)*20
! P5    = P5(V3.5)*20 + 430
! G1    = G1(V3.5)*5 + 5
! G2    = (G2(V3.5)*0.35+0.65) * P5/20
! G3    = G3(V3.5)*0.7
! PHINT = PHINT(V3.5)
 
! Converted coefficients,and those listed below,should always be
! tested by using them with real experiments and comparing model
! outputs with measured values.
 
*CULTIVARS:WHCER046
@VAR#  VAR-NAME........  EXP#   ECO#   P1V   P1D    P5    G1    G2    G3 PHINT
!                                        1     2     3     4     5     6     7
!                                     Vday %/10h  oC.d   #/g    mg     g  oC.d
920001 XIAOYAN-22           . DFAULT 58.54 107.6 532.2 23.29 39.93 1.286 141.9
 
 
999991 MINIMA               . 999991     0     0   100    10    10   0.5    30

 
DFAULT DEFAULT              . DFAULT     5    75   450    30    35   1.0    60
 
IB1500 MANITOU           1,14 CAWH01     8   100   320    23    23   2.5    86
 
IB0488 NEWTON             1,6 USWH01    45    75   500    25    30   2.0    95     !default
!IB0488 NEWTON             1,6 USWH01 31.45 31.12 800.0 30.00 27.27 1.514 65.40    ! part 125 0.0587749808003098
!IB0488 NEWTON             1,6 USWH01 24.30 22.94 800.0 30.00 31.13 1.356 65.13    ! all 73 3.28112886591024e-08
!IB0488 NEWTON             1,6 USWH01 10.67 91.65 426.5 27.60 25.55 1.318 92.16    ! glue
!IB0488 NEWTON             1,6 USWH01  8.56 48.37 479.8 27.40 30.18 1.150 60.00    ! glue
!IB0488 NEWTON             1,6 USWH01 31.53 63.17 667.8 29.50 27.93 2.100 79.50    ! 2 5.3007446715793e-10
!IB0488 NEWTON             1,6 USWH01 35.47 2.422 662.3 23.64 35.51 1.432 63.22    ! 350 2.73264165041769e-07  weight 物候期
!IB0488 NEWTON             1,6 USWH01 43.72 56.65 412.2 24.93 26.44 1.657 81.42    ! 1 7.02503630673784e-10   weight=200
 
IB1015 MARIS FUNDIN       1,8 UKWH01    30    83   515    15    44   3.2   100
!920001 XIAOYAN-22           . DFAULT 60.74 50.49 700.4 29.12 28.76 1.304 70.71
999992 MAXIMA               . 999992    60   200   999    50    80   8.0   150
XJ0001 yumo-1               . DFAULT ^P1V^ ^P1D^ 742.0 11.81 45.00 0.600 ^PHI^
!XJ0001 yumo-1               . DFAULT  48.0  130.0  692 17.81 52.00 0.500 104.0   ! 0809 结果

!XJ0001 yumo-1               . DFAULT 118.1  139.0 715.6 16.99 45.17 1.200 104.2    ! 29 0.954035826677211
!XJ0001 yumo-1               . DFAULT 100.0 130.0 760.5 23.51 45.41 1.400 136.8   ! 这个还可以
!XJ0001 yumo-1               . DFAULT 78.58 146.1 994.6 18.83 62.97 1.799 138.9    ! 1 0.696820759595399
!XJ0001 yumo-1               . DFAULT 146.2 141.3 983.7 21.71 32.10 .9530 109.9    ! 2 0.696820759595399
 
 
! COEFF       DEFINITION
! ========    ==========
! VAR#        Identification code or number for the specific cultivar.
! VAR-NAME    Name of cultivar.
! EXP#        Number of experiments used to generate parameters
! ECO#        Ecotype code for this cultivar,points to entry in ECO file
! P1V         Days,optimum vernalizing temperature,required for vernalization
! P1D         Photoperiod response (% reduction in rate/10 h drop in pp)
! P5          Grain filling (excluding lag) phase duration (oC.d)
! G1          Kernel number per unit canopy weight at anthesis (#/g)
! G2          Standard kernel size under optimum conditions (mg)
! G3          Standard,non-stressed mature tiller wt (incl grain) (g dwt)
! PHINT       Interval between successive leaf tip appearances (oC.d)
 
