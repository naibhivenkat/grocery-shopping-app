//package com.example.groceryshoppingapp.models
//
//import android.os.Parcelable
//import kotlinx.parcelize.Parcelize
//
//@Parcelize
//data class Item(
//    val id: String,
//    val name: String,
//    val description: String,
//    val price: Double,
//    val stockQuantity: Int,
//    val createdAt: String? = null,
//    val createdBy: String? = null,
//    val shopid: String,
//    val imageUrl: String? = null
//
//) : Parcelable
package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class Item(
    val id: String,
    val name: String,

    val description: String? = null,

    val price: Double,

    @SerializedName("quantity")
    val stockQuantity: Int,

    val createdAt: String? = null,
    val createdBy: String? = null,

    @SerializedName("shopId")
    val shopid: String,

    val imageUrl: String? = null
) : Parcelable
