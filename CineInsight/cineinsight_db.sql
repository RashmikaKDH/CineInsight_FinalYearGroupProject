-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Jul 22, 2026 at 12:08 PM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `cineinsight_db`
--

-- --------------------------------------------------------

--
-- Table structure for table `analysis`
--

CREATE TABLE `analysis` (
  `Analysis_Id` int(11) NOT NULL,
  `Analysis_Date` timestamp NOT NULL DEFAULT current_timestamp(),
  `Overall_Sentiment_Score` float DEFAULT NULL,
  `Sarcasm_Flag` tinyint(1) DEFAULT NULL,
  `Aspect_Vise_Report` text DEFAULT NULL,
  `User_Id` int(11) DEFAULT NULL,
  `Video_Id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `reasoning_report`
--

CREATE TABLE `reasoning_report` (
  `Report_Id` int(11) NOT NULL,
  `Generated_Text` text NOT NULL,
  `Generated_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `Analysis_Id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `user`
--

CREATE TABLE `user` (
  `User_Id` int(11) NOT NULL,
  `Name` varchar(255) NOT NULL,
  `Email` varchar(255) NOT NULL,
  `Password` varchar(255) NOT NULL,
  `Role` enum('Admin','User') DEFAULT 'User'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `user`
--

INSERT INTO `user` (`User_Id`, `Name`, `Email`, `Password`, `Role`) VALUES
(1, 'heshan', 'heshan@gmail.com', 'scrypt:32768:8:1$y18jm9boR4P5nsrh$fee2424d36532528ee266489cb5d39e1d91f034a18f8fc171ff3c1ce399bb3100b324a6bdab8546320f31f2a25b7ab5bb7ca32eff4f55ad7405d201145645357', 'User'),
(2, 'CineInsight Admin', 'admin@cineinsight.com', 'scrypt:32768:8:1$fl3lDyrYzFhGUptN$f89d7dce5d445d2ba5f171d2e5b2c16f15d12b8b558075d65f57f1d3fe0061d05bd1f8897bd2f61760b995b017bb0adb511fe9435b1de04bb6655c0b759fdd73', 'Admin');

-- --------------------------------------------------------

--
-- Table structure for table `youtube_video`
--

CREATE TABLE `youtube_video` (
  `Video_Id` int(11) NOT NULL,
  `Title` varchar(255) NOT NULL,
  `YouTube_url` varchar(500) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `analysis`
--
ALTER TABLE `analysis`
  ADD PRIMARY KEY (`Analysis_Id`),
  ADD KEY `User_Id` (`User_Id`),
  ADD KEY `Video_Id` (`Video_Id`);

--
-- Indexes for table `reasoning_report`
--
ALTER TABLE `reasoning_report`
  ADD PRIMARY KEY (`Report_Id`),
  ADD UNIQUE KEY `Analysis_Id` (`Analysis_Id`);

--
-- Indexes for table `user`
--
ALTER TABLE `user`
  ADD PRIMARY KEY (`User_Id`),
  ADD UNIQUE KEY `Email` (`Email`);

--
-- Indexes for table `youtube_video`
--
ALTER TABLE `youtube_video`
  ADD PRIMARY KEY (`Video_Id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `analysis`
--
ALTER TABLE `analysis`
  MODIFY `Analysis_Id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `reasoning_report`
--
ALTER TABLE `reasoning_report`
  MODIFY `Report_Id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `user`
--
ALTER TABLE `user`
  MODIFY `User_Id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT for table `youtube_video`
--
ALTER TABLE `youtube_video`
  MODIFY `Video_Id` int(11) NOT NULL AUTO_INCREMENT;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `analysis`
--
ALTER TABLE `analysis`
  ADD CONSTRAINT `analysis_ibfk_1` FOREIGN KEY (`User_Id`) REFERENCES `user` (`User_Id`) ON DELETE SET NULL,
  ADD CONSTRAINT `analysis_ibfk_2` FOREIGN KEY (`Video_Id`) REFERENCES `youtube_video` (`Video_Id`) ON DELETE CASCADE;

--
-- Constraints for table `reasoning_report`
--
ALTER TABLE `reasoning_report`
  ADD CONSTRAINT `reasoning_report_ibfk_1` FOREIGN KEY (`Analysis_Id`) REFERENCES `analysis` (`Analysis_Id`) ON DELETE CASCADE;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
